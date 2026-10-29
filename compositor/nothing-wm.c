/*
 * nothing-wm — Wayland compositor of the Nothing desktop.
 *
 * Built on wlroots 0.20. Provides xdg-shell + XWayland windows, layer-shell
 * for the shell components (bar, dock, desktop widgets), virtual workspaces,
 * session lock and a small line based IPC socket the shell talks to.
 */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <linux/input-event-codes.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <wayland-server-core.h>
#include <xkbcommon/xkbcommon.h>

#include <wlr/backend.h>
#include <wlr/backend/session.h>
#include <wlr/render/allocator.h>
#include <wlr/render/wlr_renderer.h>
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_cursor.h>
#include <wlr/types/wlr_cursor_shape_v1.h>
#include <wlr/types/wlr_data_control_v1.h>
#include <wlr/types/wlr_data_device.h>
#include <wlr/types/wlr_export_dmabuf_v1.h>
#include <wlr/types/wlr_ext_data_control_v1.h>
#include <wlr/types/wlr_ext_image_capture_source_v1.h>
#include <wlr/types/wlr_ext_image_copy_capture_v1.h>
#include <wlr/types/wlr_fractional_scale_v1.h>
#include <wlr/types/wlr_gamma_control_v1.h>
#include <wlr/types/wlr_idle_inhibit_v1.h>
#include <wlr/types/wlr_idle_notify_v1.h>
#include <wlr/types/wlr_input_device.h>
#include <wlr/types/wlr_keyboard.h>
#include <wlr/types/wlr_layer_shell_v1.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_pointer.h>
#include <wlr/types/wlr_presentation_time.h>
#include <wlr/types/wlr_primary_selection.h>
#include <wlr/types/wlr_primary_selection_v1.h>
#include <wlr/types/wlr_relative_pointer_v1.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_screencopy_v1.h>
#include <wlr/types/wlr_seat.h>
#include <wlr/types/wlr_server_decoration.h>
#include <wlr/types/wlr_session_lock_v1.h>
#include <wlr/types/wlr_single_pixel_buffer_v1.h>
#include <wlr/types/wlr_subcompositor.h>
#include <wlr/types/wlr_tablet_tool.h>
#include <wlr/types/wlr_tablet_v2.h>
#include <wlr/types/wlr_touch.h>
#include <wlr/types/wlr_viewporter.h>
#include <wlr/types/wlr_xcursor_manager.h>
#include <wlr/types/wlr_xdg_activation_v1.h>
#include <wlr/types/wlr_xdg_output_v1.h>
#include <wlr/types/wlr_xdg_shell.h>
#include <wlr/util/log.h>
#include <wlr/xwayland.h>
#include <xcb/xproto.h>

#define MAX_WS 10
#define TITLE_H 30
#define BTN_SIZE 12
#define MAX_TOUCH_POINTS 10

enum node_kind { NODE_VIEW = 1, NODE_LAYER, NODE_UNMANAGED };

/* scene stacking order, bottom to top */
enum {
	LYR_BACKGROUND,
	LYR_BOTTOM,
	LYR_WINDOWS,
	LYR_TOP,
	LYR_UNMANAGED,
	LYR_FULLSCREEN,
	LYR_OVERLAY,
	LYR_DRAG,
	LYR_LOCK,
	LYR_COUNT,
};

enum cursor_mode { CUR_PASSTHROUGH, CUR_MOVE, CUR_RESIZE };
enum view_type { VIEW_XDG, VIEW_X11 };

struct server;

struct output {
	struct wl_list link;
	struct server *server;
	struct wlr_output *wlr_output;
	struct wlr_scene_output *scene_output;
	struct wlr_box full, usable;
	struct wl_listener frame, request_state, destroy;
};

struct view {
	enum node_kind kind;
	struct wl_list link; /* server.views, most recently focused first */
	struct server *server;
	enum view_type type;
	uint32_t id;
	struct wlr_xdg_toplevel *xdg;
	struct wlr_xwayland_surface *xsurface;

	struct wlr_scene_tree *tree;
	struct wlr_scene_tree *content;
	struct wlr_scene_tree *deco;
	struct wlr_scene_rect *titlebar, *btn_close, *btn_min, *btn_max;
	bool ssd;

	int x, y; /* layout position of the visible window area */
	int ws;
	bool mapped, minimized, maximized, fullscreen, placed;
	struct wlr_box saved;

	struct wl_listener map, unmap, commit, destroy;
	struct wl_listener request_move, request_resize, request_maximize,
		request_fullscreen, request_minimize, set_title, set_app_id;
	/* xwayland only */
	struct wl_listener associate, dissociate, request_configure,
		request_activate, set_decorations;
};

struct unmanaged {
	enum node_kind kind;
	struct server *server;
	struct wlr_xwayland_surface *xsurface;
	struct wlr_scene_tree *tree;
	struct wl_listener associate, dissociate, map, unmap, destroy,
		set_geometry, request_configure;
};

struct layer {
	enum node_kind kind;
	struct wl_list link;
	struct server *server;
	struct wlr_layer_surface_v1 *surface;
	struct wlr_scene_layer_surface_v1 *scene;
	struct wlr_scene_tree *popups;
	struct output *output;
	bool mapped;
	struct wl_listener map, unmap, commit, destroy, new_popup;
};

struct popup {
	struct wlr_xdg_popup *xdg_popup;
	struct wl_listener commit, destroy;
};

struct keyboard {
	struct wl_list link;
	struct server *server;
	struct wlr_keyboard *wlr_keyboard;
	struct wl_listener modifiers, key, destroy;
};

struct ipc_client {
	struct wl_list link;
	struct server *server;
	int fd;
	struct wl_event_source *source;
	char buf[8192];
	size_t len;
	bool subscribed;
};

struct lock_surface {
	struct server *server;
	struct wlr_session_lock_surface_v1 *surface;
	struct wl_listener map, destroy;
};

/* a touch point stays glued to the surface it went down on; we remember
 * that surface's origin in layout coordinates so later motion events can
 * be translated into coordinates local to it */
struct touch_point {
	bool active;
	int32_t id;
	struct wlr_surface *surface;
	double ox, oy;
};

struct server {
	struct wl_display *display;
	struct wl_event_loop *loop;
	struct wlr_backend *backend;
	struct wlr_session *session;
	struct wlr_renderer *renderer;
	struct wlr_allocator *allocator;
	struct wlr_compositor *compositor;
	struct wlr_scene *scene;
	struct wlr_scene_output_layout *scene_layout;
	struct wlr_scene_tree *layers[LYR_COUNT];
	struct wlr_scene_tree *ws_tree[MAX_WS];
	struct wlr_output_layout *output_layout;

	struct wlr_xdg_shell *xdg_shell;
	struct wlr_layer_shell_v1 *layer_shell;
	struct wlr_xwayland *xwayland;
	struct wlr_xdg_activation_v1 *activation;
	struct wlr_relative_pointer_manager_v1 *relative_pointer;
	struct wlr_cursor_shape_manager_v1 *cursor_shape;
	struct wlr_session_lock_manager_v1 *lock_manager;
	struct wlr_tablet_manager_v2 *tablet_mgr;

	struct wlr_cursor *cursor;
	struct wlr_xcursor_manager *xcursor_mgr;
	struct wlr_seat *seat;

	struct wl_list outputs, views, layers_list, keyboards, ipc_clients;
	int n_touch;
	struct touch_point touch_points[MAX_TOUCH_POINTS];
	float out_scale;

	enum cursor_mode cursor_mode;
	struct view *grabbed;
	double grab_x, grab_y;
	struct wlr_box grab_box;
	uint32_t resize_edges;

	struct layer *focused_layer;

	/* drag and drop */
	struct wlr_scene_tree *drag_icon;
	struct wl_listener drag_destroy;
	int cur_ws, n_ws;
	uint32_t next_id;

	/* session lock */
	struct wlr_session_lock_v1 *lock;
	bool locked;
	struct wlr_scene_rect *lock_bg;
	struct wl_listener lock_new_surface, lock_unlock, lock_destroy;

	/* runtime config pushed by the shell */
	float accent[4];
	bool dark;
	char kb_layout[64], kb_variant[64], kb_options[128];

	int ipc_fd;
	char ipc_path[108];
	struct wl_event_source *state_idle;

	struct wl_listener new_output, new_input, new_xdg_toplevel, new_xdg_popup,
		new_layer, xwayland_ready, new_xsurface, cursor_motion,
		cursor_motion_abs, cursor_button, cursor_axis, cursor_frame,
		request_cursor, request_set_selection, request_set_primary,
		request_activate, request_set_shape, new_lock, request_start_drag,
		start_drag;
	struct wl_listener touch_down, touch_up, touch_motion, touch_cancel, touch_frame,
		tablet_tool_axis, tablet_tool_proximity, tablet_tool_tip, tablet_tool_button;
};

static void focus_view(struct view *view);
static void focus_top_view(struct server *server);
static void schedule_state(struct server *server);
static void ipc_broadcast(struct server *server, const char *msg);
static void view_set_visible(struct view *view);
static void view_maximize(struct view *view, bool on);
static void view_fullscreen(struct view *view, bool on);
static void update_output_boxes(struct server *s);

/* ------------------------------------------------------------------ */
/* helpers                                                            */

static void spawn(const char *cmd) {
	/* double fork: the grandchild is reparented to init, so no zombies and
	 * no need to ignore SIGCHLD (which would break Xwayland's xkbcomp) */
	pid_t pid = fork();
	if (pid == 0) {
		setsid();
		sigset_t set;
		sigemptyset(&set);
		sigprocmask(SIG_SETMASK, &set, NULL);
		signal(SIGPIPE, SIG_DFL);
		if (fork() == 0) {
			execl("/bin/sh", "/bin/sh", "-c", cmd, (void *)NULL);
			_exit(127);
		}
		_exit(0);
	} else if (pid > 0) {
		waitpid(pid, NULL, 0);
	}
}

static const char *view_title(struct view *v) {
	const char *t = v->type == VIEW_XDG ? v->xdg->title : v->xsurface->title;
	return t ? t : "";
}

static const char *view_app_id(struct view *v) {
	const char *t = v->type == VIEW_XDG ? v->xdg->app_id : v->xsurface->class;
	return t ? t : "";
}

static struct wlr_surface *view_surface(struct view *v) {
	return v->type == VIEW_XDG ? v->xdg->base->surface : v->xsurface->surface;
}

static struct wlr_box view_geometry(struct view *v) {
	struct wlr_box box = {0};
	if (v->type == VIEW_XDG) {
		box = v->xdg->base->geometry;
	} else {
		box.width = v->xsurface->width;
		box.height = v->xsurface->height;
	}
	return box;
}

static struct output *output_at(struct server *s, double x, double y) {
	struct wlr_output *o = wlr_output_layout_output_at(s->output_layout, x, y);
	struct output *out;
	wl_list_for_each(out, &s->outputs, link) {
		if (out->wlr_output == o) {
			return out;
		}
	}
	if (!wl_list_empty(&s->outputs)) {
		return wl_container_of(s->outputs.next, out, link);
	}
	return NULL;
}

static struct output *view_output(struct view *v) {
	struct wlr_box g = view_geometry(v);
	return output_at(v->server, v->x + g.width / 2.0, v->y + g.height / 2.0);
}

static void parse_color(const char *hex, float out[4]) {
	unsigned r = 0xd7, g = 0x19, b = 0x21;
	if (hex && hex[0] == '#' && strlen(hex) >= 7) {
		sscanf(hex + 1, "%02x%02x%02x", &r, &g, &b);
	}
	out[0] = r / 255.0f;
	out[1] = g / 255.0f;
	out[2] = b / 255.0f;
	out[3] = 1.0f;
}

/* ------------------------------------------------------------------ */
/* server side decorations (X11 windows only — Wayland apps draw CSD) */

static void deco_update(struct view *v) {
	if (!v->deco) {
		return;
	}
	wlr_scene_node_set_enabled(&v->deco->node, v->ssd && !v->fullscreen);
	if (!v->ssd) {
		return;
	}
	struct wlr_box g = view_geometry(v);
	float bar[4] = {0.106f, 0.106f, 0.114f, 1.0f};
	float grey[4] = {0.35f, 0.35f, 0.37f, 1.0f};
	if (!v->server->dark) {
		bar[0] = bar[1] = bar[2] = 0.94f;
		grey[0] = grey[1] = grey[2] = 0.70f;
	}
	wlr_scene_node_set_position(&v->deco->node, 0, -TITLE_H);
	wlr_scene_rect_set_size(v->titlebar, g.width, TITLE_H);
	wlr_scene_rect_set_color(v->titlebar, bar);
	int y = (TITLE_H - BTN_SIZE) / 2;
	wlr_scene_node_set_position(&v->btn_close->node, 14, y);
	wlr_scene_node_set_position(&v->btn_min->node, 14 + BTN_SIZE + 8, y);
	wlr_scene_node_set_position(&v->btn_max->node, 14 + 2 * (BTN_SIZE + 8), y);
	wlr_scene_rect_set_color(v->btn_close, v->server->accent);
	wlr_scene_rect_set_color(v->btn_min, grey);
	wlr_scene_rect_set_color(v->btn_max, grey);
}

static void deco_create(struct view *v) {
	float c[4] = {0, 0, 0, 1};
	v->deco = wlr_scene_tree_create(v->tree);
	v->titlebar = wlr_scene_rect_create(v->deco, 1, TITLE_H, c);
	v->btn_close = wlr_scene_rect_create(v->deco, BTN_SIZE, BTN_SIZE, c);
	v->btn_min = wlr_scene_rect_create(v->deco, BTN_SIZE, BTN_SIZE, c);
	v->btn_max = wlr_scene_rect_create(v->deco, BTN_SIZE, BTN_SIZE, c);
	wlr_scene_node_lower_to_bottom(&v->deco->node);
	deco_update(v);
}

static int view_top_offset(struct view *v) {
	return (v->ssd && !v->fullscreen) ? TITLE_H : 0;
}

/* ------------------------------------------------------------------ */
/* view placement / geometry                                          */

static void view_move(struct view *v, int x, int y) {
	v->x = x;
	v->y = y;
	wlr_scene_node_set_position(&v->tree->node, x, y);
	if (v->type == VIEW_X11 && v->xsurface->surface) {
		wlr_xwayland_surface_configure(v->xsurface, x, y,
			v->xsurface->width, v->xsurface->height);
	}
}

static void view_configure(struct view *v, int x, int y, int w, int h) {
	if (w < 1 || h < 1) {
		return;
	}
	v->x = x;
	v->y = y;
	wlr_scene_node_set_position(&v->tree->node, x, y);
	if (v->type == VIEW_XDG) {
		wlr_xdg_toplevel_set_size(v->xdg, w, h);
	} else {
		wlr_xwayland_surface_configure(v->xsurface, x, y, w, h);
	}
}

static void view_place(struct view *v) {
	struct server *s = v->server;
	struct output *out = output_at(s, s->cursor->x, s->cursor->y);
	if (!out) {
		return;
	}
	struct wlr_box g = view_geometry(v);
	struct wlr_box *a = &out->usable;
	int top = view_top_offset(v);
	int x, y;
	if (v->type == VIEW_X11 && (v->xsurface->x || v->xsurface->y) &&
			wlr_output_layout_contains_point(s->output_layout, NULL,
				v->xsurface->x, v->xsurface->y)) {
		x = v->xsurface->x;
		y = v->xsurface->y;
	} else {
		static int cascade = 0;
		cascade = (cascade + 1) % 6;
		x = a->x + (a->width - g.width) / 2 + (cascade - 3) * 24;
		y = a->y + (a->height - g.height - top) / 2 + top + (cascade - 3) * 24;
	}
	if (x + g.width > a->x + a->width) x = a->x + a->width - g.width;
	if (y + g.height > a->y + a->height) y = a->y + a->height - g.height;
	if (x < a->x) x = a->x;
	if (y < a->y + top) y = a->y + top;
	view_move(v, x, y);
	v->placed = true;
}

static void view_maximize(struct view *v, bool on) {
	if (v->fullscreen || v->maximized == on) {
		if (v->type == VIEW_XDG && v->xdg->base->initialized) {
			wlr_xdg_surface_schedule_configure(v->xdg->base);
		}
		return;
	}
	struct output *out = view_output(v);
	if (!out) {
		return;
	}
	if (on) {
		struct wlr_box g = view_geometry(v);
		v->saved = (struct wlr_box){v->x, v->y, g.width, g.height};
		int top = view_top_offset(v);
		view_configure(v, out->usable.x, out->usable.y + top,
			out->usable.width, out->usable.height - top);
	} else if (v->saved.width > 0) {
		view_configure(v, v->saved.x, v->saved.y, v->saved.width, v->saved.height);
	}
	v->maximized = on;
	if (v->type == VIEW_XDG) {
		wlr_xdg_toplevel_set_maximized(v->xdg, on);
	} else {
		wlr_xwayland_surface_set_maximized(v->xsurface, on, on);
	}
}

static void view_fullscreen(struct view *v, bool on) {
	if (v->fullscreen == on) {
		if (v->type == VIEW_XDG && v->xdg->base->initialized) {
			wlr_xdg_surface_schedule_configure(v->xdg->base);
		}
		return;
	}
	struct server *s = v->server;
	struct output *out = view_output(v);
	if (!out) {
		return;
	}
	if (on) {
		if (!v->maximized) {
			struct wlr_box g = view_geometry(v);
			v->saved = (struct wlr_box){v->x, v->y, g.width, g.height};
		}
		v->fullscreen = true;
		wlr_scene_node_reparent(&v->tree->node, s->layers[LYR_FULLSCREEN]);
		view_configure(v, out->full.x, out->full.y, out->full.width, out->full.height);
	} else {
		v->fullscreen = false;
		wlr_scene_node_reparent(&v->tree->node, s->ws_tree[v->ws]);
		if (v->maximized) {
			int top = view_top_offset(v);
			view_configure(v, out->usable.x, out->usable.y + top,
				out->usable.width, out->usable.height - top);
		} else if (v->saved.width > 0) {
			view_configure(v, v->saved.x, v->saved.y, v->saved.width, v->saved.height);
		}
	}
	if (v->type == VIEW_XDG) {
		wlr_xdg_toplevel_set_fullscreen(v->xdg, on);
	} else {
		wlr_xwayland_surface_set_fullscreen(v->xsurface, on);
	}
	deco_update(v);
	view_set_visible(v);
	schedule_state(s);
}

static void view_set_visible(struct view *v) {
	bool vis = v->mapped && !v->minimized && v->ws == v->server->cur_ws;
	wlr_scene_node_set_enabled(&v->tree->node, vis);
}

static void view_minimize(struct view *v, bool on) {
	struct server *s = v->server;
	v->minimized = on;
	if (v->type == VIEW_X11) {
		wlr_xwayland_surface_set_minimized(v->xsurface, on);
	}
	view_set_visible(v);
	if (on) {
		/* push to the back of the focus order */
		wl_list_remove(&v->link);
		wl_list_insert(s->views.prev, &v->link);
		focus_top_view(s);
	} else {
		focus_view(v);
	}
	schedule_state(s);
}

static void view_close(struct view *v) {
	if (v->type == VIEW_XDG) {
		wlr_xdg_toplevel_send_close(v->xdg);
	} else {
		wlr_xwayland_surface_close(v->xsurface);
	}
}

/* ------------------------------------------------------------------ */
/* workspaces                                                         */

static void switch_workspace(struct server *s, int ws) {
	if (ws < 0 || ws >= s->n_ws || ws == s->cur_ws) {
		return;
	}
	s->cur_ws = ws;
	for (int i = 0; i < MAX_WS; i++) {
		wlr_scene_node_set_enabled(&s->ws_tree[i]->node, i == ws);
	}
	struct view *v;
	wl_list_for_each(v, &s->views, link) {
		view_set_visible(v);
	}
	focus_top_view(s);
	schedule_state(s);
}

static void view_to_workspace(struct view *v, int ws) {
	struct server *s = v->server;
	if (ws < 0 || ws >= s->n_ws || ws == v->ws) {
		return;
	}
	v->ws = ws;
	if (!v->fullscreen) {
		wlr_scene_node_reparent(&v->tree->node, s->ws_tree[ws]);
	}
	view_set_visible(v);
	focus_top_view(s);
	schedule_state(s);
}

static void set_workspace_count(struct server *s, int n) {
	if (n < 1) n = 1;
	if (n > MAX_WS) n = MAX_WS;
	s->n_ws = n;
	struct view *v;
	wl_list_for_each(v, &s->views, link) {
		if (v->ws >= n) {
			v->ws = n - 1;
			if (!v->fullscreen) {
				wlr_scene_node_reparent(&v->tree->node, s->ws_tree[v->ws]);
			}
		}
	}
	if (s->cur_ws >= n) {
		int target = n - 1;
		s->cur_ws = -1;
		switch_workspace(s, target);
	}
	wl_list_for_each(v, &s->views, link) {
		view_set_visible(v);
	}
	schedule_state(s);
}

/* ------------------------------------------------------------------ */
/* focus                                                              */

static struct view *view_from_surface(struct server *s, struct wlr_surface *surface) {
	if (!surface) {
		return NULL;
	}
	struct view *v;
	wl_list_for_each(v, &s->views, link) {
		if (view_surface(v) == surface) {
			return v;
		}
	}
	return NULL;
}

static void keyboard_enter(struct server *s, struct wlr_surface *surface) {
	struct wlr_keyboard *kb = wlr_seat_get_keyboard(s->seat);
	if (!surface) {
		wlr_seat_keyboard_notify_clear_focus(s->seat);
		return;
	}
	if (kb) {
		wlr_seat_keyboard_notify_enter(s->seat, surface, kb->keycodes,
			kb->num_keycodes, &kb->modifiers);
	} else {
		wlr_seat_keyboard_notify_enter(s->seat, surface, NULL, 0, NULL);
	}
}

static void view_activate(struct view *v, bool on) {
	if (v->type == VIEW_XDG) {
		wlr_xdg_toplevel_set_activated(v->xdg, on);
	} else if (v->xsurface->surface) {
		wlr_xwayland_surface_activate(v->xsurface, on);
	}
}

static void focus_view(struct view *v) {
	struct server *s = v->server;
	if (s->locked || !v->mapped) {
		return;
	}
	if (v->ws != s->cur_ws) {
		switch_workspace(s, v->ws);
	}
	if (v->minimized) {
		v->minimized = false;
		if (v->type == VIEW_X11) {
			wlr_xwayland_surface_set_minimized(v->xsurface, false);
		}
		view_set_visible(v);
	}
	struct wlr_surface *prev = s->seat->keyboard_state.focused_surface;
	struct view *pv = view_from_surface(s, prev);
	if (pv && pv != v) {
		view_activate(pv, false);
	}
	wl_list_remove(&v->link);
	wl_list_insert(&s->views, &v->link);
	wlr_scene_node_raise_to_top(&v->tree->node);
	if (v->type == VIEW_X11) {
		wlr_xwayland_surface_restack(v->xsurface, NULL, XCB_STACK_MODE_ABOVE);
	}
	view_activate(v, true);
	/* an exclusive layer surface (launcher etc.) keeps the keyboard */
	if (!s->focused_layer || s->focused_layer->surface->current.keyboard_interactive !=
			ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_EXCLUSIVE) {
		s->focused_layer = NULL;
		keyboard_enter(s, view_surface(v));
	}
	schedule_state(s);
}

static struct view *top_view(struct server *s) {
	struct view *v;
	wl_list_for_each(v, &s->views, link) {
		if (v->mapped && !v->minimized && v->ws == s->cur_ws) {
			return v;
		}
	}
	return NULL;
}

static void focus_top_view(struct server *s) {
	if (s->locked) {
		return;
	}
	if (s->focused_layer) {
		keyboard_enter(s, s->focused_layer->surface->surface);
		return;
	}
	struct view *v = top_view(s);
	if (v) {
		focus_view(v);
	} else {
		struct view *pv = view_from_surface(s, s->seat->keyboard_state.focused_surface);
		if (pv) {
			view_activate(pv, false);
		}
		keyboard_enter(s, NULL);
		schedule_state(s);
	}
}

static uint32_t focused_view_id(struct server *s) {
	struct view *v = view_from_surface(s, s->seat->keyboard_state.focused_surface);
	return v ? v->id : 0;
}

/* ------------------------------------------------------------------ */
/* IPC                                                                */

static void json_escape(FILE *f, const char *str) {
	fputc('"', f);
	for (const unsigned char *p = (const unsigned char *)str; *p; p++) {
		if (*p == '"' || *p == '\\') {
			fputc('\\', f);
			fputc(*p, f);
		} else if (*p < 0x20) {
			fprintf(f, "\\u%04x", *p);
		} else {
			fputc(*p, f);
		}
	}
	fputc('"', f);
}

static char *build_state(struct server *s) {
	char *buf = NULL;
	size_t len = 0;
	FILE *f = open_memstream(&buf, &len);
	fprintf(f, "{\"event\":\"state\",\"workspace\":%d,\"workspaces\":%d,"
		"\"focused\":%u,\"locked\":%s,\"windows\":[",
		s->cur_ws + 1, s->n_ws, focused_view_id(s), s->locked ? "true" : "false");
	bool first = true;
	struct view *v;
	/* stable ordering by id so the dock does not jump around */
	for (uint32_t id = 1; id < s->next_id; id++) {
		wl_list_for_each(v, &s->views, link) {
			if (v->id != id || !v->mapped) {
				continue;
			}
			if (v->type == VIEW_X11 && v->xsurface->skip_taskbar) {
				continue;
			}
			fprintf(f, "%s{\"id\":%u,\"app_id\":", first ? "" : ",", v->id);
			json_escape(f, view_app_id(v));
			fprintf(f, ",\"title\":");
			json_escape(f, view_title(v));
			pid_t pid = 0;
			if (v->type == VIEW_X11) {
				pid = v->xsurface->pid;
			} else {
				wl_client_get_credentials(v->xdg->base->client->client, &pid, NULL, NULL);
			}
			fprintf(f, ",\"ws\":%d,\"minimized\":%s,\"maximized\":%s,"
				"\"fullscreen\":%s,\"x11\":%s,\"pid\":%d}",
				v->ws + 1, v->minimized ? "true" : "false",
				v->maximized ? "true" : "false",
				v->fullscreen ? "true" : "false",
				v->type == VIEW_X11 ? "true" : "false", (int)pid);
			first = false;
		}
	}
	fprintf(f, "]}\n");
	fclose(f);
	return buf;
}

static void ipc_client_destroy(struct ipc_client *c) {
	wl_event_source_remove(c->source);
	close(c->fd);
	wl_list_remove(&c->link);
	free(c);
}

static bool ipc_send(struct ipc_client *c, const char *msg) {
	size_t len = strlen(msg);
	ssize_t n = send(c->fd, msg, len, MSG_NOSIGNAL | MSG_DONTWAIT);
	return n == (ssize_t)len;
}

static void ipc_broadcast(struct server *s, const char *msg) {
	struct ipc_client *c, *tmp;
	wl_list_for_each_safe(c, tmp, &s->ipc_clients, link) {
		if (c->subscribed && !ipc_send(c, msg)) {
			ipc_client_destroy(c);
		}
	}
}

static void send_action(struct server *s, const char *name) {
	char msg[128];
	snprintf(msg, sizeof(msg), "{\"event\":\"action\",\"name\":\"%s\"}\n", name);
	ipc_broadcast(s, msg);
}

static void state_idle_cb(void *data) {
	struct server *s = data;
	s->state_idle = NULL;
	char *st = build_state(s);
	ipc_broadcast(s, st);
	free(st);
}

static void schedule_state(struct server *s) {
	if (!s->state_idle) {
		s->state_idle = wl_event_loop_add_idle(s->loop, state_idle_cb, s);
	}
}

static struct view *view_by_id(struct server *s, uint32_t id) {
	struct view *v;
	wl_list_for_each(v, &s->views, link) {
		if (v->id == id && v->mapped) {
			return v;
		}
	}
	return NULL;
}

static void apply_keymap(struct server *s) {
	struct xkb_rule_names rules = {0};
	rules.layout = s->kb_layout[0] ? s->kb_layout : NULL;
	rules.variant = s->kb_variant[0] ? s->kb_variant : NULL;
	rules.options = s->kb_options[0] ? s->kb_options : NULL;
	struct xkb_context *ctx = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
	struct xkb_keymap *km = xkb_keymap_new_from_names(ctx, &rules,
		XKB_KEYMAP_COMPILE_NO_FLAGS);
	if (!km) {
		wlr_log(WLR_ERROR, "invalid keymap %s/%s", s->kb_layout, s->kb_variant);
		xkb_context_unref(ctx);
		return;
	}
	struct keyboard *k;
	wl_list_for_each(k, &s->keyboards, link) {
		wlr_keyboard_set_keymap(k->wlr_keyboard, km);
	}
	xkb_keymap_unref(km);
	xkb_context_unref(ctx);
}

static void ipc_handle(struct ipc_client *c, char *line) {
	struct server *s = c->server;
	char *save = NULL;
	char *cmd = strtok_r(line, " \t", &save);
	if (!cmd) {
		return;
	}
	char *a1 = strtok_r(NULL, " \t", &save);
	char *rest = save;
	uint32_t id = a1 ? (uint32_t)strtoul(a1, NULL, 10) : 0;
	struct view *v = view_by_id(s, id);

	if (!strcmp(cmd, "subscribe")) {
		c->subscribed = true;
		char *st = build_state(s);
		ipc_send(c, st);
		free(st);
	} else if (!strcmp(cmd, "state")) {
		char *st = build_state(s);
		ipc_send(c, st);
		free(st);
	} else if (!strcmp(cmd, "focus") && v) {
		focus_view(v);
	} else if (!strcmp(cmd, "toggle") && v) {
		if (!v->minimized && v->ws == s->cur_ws && focused_view_id(s) == v->id) {
			view_minimize(v, true);
		} else {
			focus_view(v);
		}
	} else if (!strcmp(cmd, "close") && v) {
		view_close(v);
	} else if (!strcmp(cmd, "minimize") && v) {
		view_minimize(v, true);
	} else if (!strcmp(cmd, "maximize") && v) {
		view_maximize(v, !v->maximized);
	} else if (!strcmp(cmd, "fullscreen") && v) {
		view_fullscreen(v, !v->fullscreen);
	} else if (!strcmp(cmd, "geometry") && v && rest) {
		int gx, gy, gw, gh;
		if (sscanf(rest, "%d %d %d %d", &gx, &gy, &gw, &gh) == 4 && !v->fullscreen) {
			if (v->maximized) {
				view_maximize(v, false);
			}
			view_configure(v, gx, gy, gw, gh);
			deco_update(v);
		}
	} else if (!strcmp(cmd, "ws") && a1) {
		switch_workspace(s, atoi(a1) - 1);
	} else if (!strcmp(cmd, "move") && v && rest) {
		view_to_workspace(v, atoi(rest) - 1);
	} else if (!strcmp(cmd, "show_desktop")) {
		wl_list_for_each(v, &s->views, link) {
			if (v->mapped && v->ws == s->cur_ws && !v->minimized) {
				v->minimized = true;
				view_set_visible(v);
			}
		}
		focus_top_view(s);
		schedule_state(s);
	} else if (!strcmp(cmd, "config") && a1) {
		const char *val = rest ? rest : "";
		while (*val == ' ') val++;
		if (!strcmp(a1, "workspaces")) {
			set_workspace_count(s, atoi(val));
		} else if (!strcmp(a1, "accent")) {
			parse_color(val, s->accent);
		} else if (!strcmp(a1, "dark")) {
			s->dark = atoi(val) != 0;
		} else if (!strcmp(a1, "kb_layout")) {
			snprintf(s->kb_layout, sizeof(s->kb_layout), "%s", val);
			apply_keymap(s);
		} else if (!strcmp(a1, "kb_variant")) {
			snprintf(s->kb_variant, sizeof(s->kb_variant), "%s", val);
			apply_keymap(s);
		} else if (!strcmp(a1, "kb_options")) {
			snprintf(s->kb_options, sizeof(s->kb_options), "%s", val);
			apply_keymap(s);
		} else if (!strcmp(a1, "cursor_theme")) {
			setenv("XCURSOR_THEME", val, 1);
		} else if (!strcmp(a1, "scale")) {
			float sc = atof(val);
			if (sc > 0) {
				s->out_scale = sc;
				struct output *o;
				wl_list_for_each(o, &s->outputs, link) {
					struct wlr_output_state st;
					wlr_output_state_init(&st);
					wlr_output_state_set_scale(&st, sc);
					wlr_output_commit_state(o->wlr_output, &st);
					wlr_output_state_finish(&st);
				}
				update_output_boxes(s);
				schedule_state(s);
			}
		}
		wl_list_for_each(v, &s->views, link) {
			deco_update(v);
		}
	} else if (!strcmp(cmd, "action") && a1) {
		send_action(s, a1);
	} else if (!strcmp(cmd, "exit")) {
		wl_display_terminate(s->display);
	} else {
		ipc_send(c, "{\"event\":\"error\"}\n");
	}
}

static int ipc_client_readable(int fd, uint32_t mask, void *data) {
	struct ipc_client *c = data;
	if (mask & (WL_EVENT_HANGUP | WL_EVENT_ERROR)) {
		ipc_client_destroy(c);
		return 0;
	}
	ssize_t n = read(fd, c->buf + c->len, sizeof(c->buf) - c->len - 1);
	if (n <= 0) {
		if (n < 0 && errno == EAGAIN) {
			return 0;
		}
		ipc_client_destroy(c);
		return 0;
	}
	c->len += n;
	c->buf[c->len] = '\0';
	char *start = c->buf, *nl;
	while ((nl = strchr(start, '\n'))) {
		*nl = '\0';
		ipc_handle(c, start);
		start = nl + 1;
	}
	c->len = strlen(start);
	memmove(c->buf, start, c->len);
	if (c->len >= sizeof(c->buf) - 1) {
		c->len = 0; /* overlong line, drop it */
	}
	return 0;
}

static int ipc_accept(int fd, uint32_t mask, void *data) {
	struct server *s = data;
	int cfd = accept4(fd, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
	if (cfd < 0) {
		return 0;
	}
	struct ipc_client *c = calloc(1, sizeof(*c));
	c->server = s;
	c->fd = cfd;
	c->source = wl_event_loop_add_fd(s->loop, cfd, WL_EVENT_READABLE,
		ipc_client_readable, c);
	wl_list_insert(&s->ipc_clients, &c->link);
	return 0;
}

static bool ipc_init(struct server *s, const char *socket_name) {
	const char *rt = getenv("XDG_RUNTIME_DIR");
	if (!rt) {
		return false;
	}
	snprintf(s->ipc_path, sizeof(s->ipc_path), "%s/nothing-wm.%s.sock", rt, socket_name);
	unlink(s->ipc_path);
	s->ipc_fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
	struct sockaddr_un addr = {.sun_family = AF_UNIX};
	snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", s->ipc_path);
	if (bind(s->ipc_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0 ||
			listen(s->ipc_fd, 8) < 0) {
		wlr_log_errno(WLR_ERROR, "ipc socket");
		return false;
	}
	wl_event_loop_add_fd(s->loop, s->ipc_fd, WL_EVENT_READABLE, ipc_accept, s);
	setenv("NOTHING_WM_SOCK", s->ipc_path, 1);
	return true;
}

/* ------------------------------------------------------------------ */
/* keyboard                                                           */

static bool handle_keybinding(struct server *s, xkb_keysym_t sym, uint32_t mods) {
	if (sym >= XKB_KEY_XF86Switch_VT_1 && sym <= XKB_KEY_XF86Switch_VT_12) {
		if (s->session) {
			wlr_session_change_vt(s->session, sym - XKB_KEY_XF86Switch_VT_1 + 1);
		}
		return true;
	}
	if (s->locked) {
		return false;
	}
	struct view *focused = view_from_surface(s, s->seat->keyboard_state.focused_surface);
	bool super = mods & WLR_MODIFIER_LOGO;
	bool shift = mods & WLR_MODIFIER_SHIFT;
	bool ctrl = mods & WLR_MODIFIER_CTRL;

	if ((mods & WLR_MODIFIER_ALT) && sym == XKB_KEY_Tab) {
		/* focus the least recently used window -> cycles through all */
		struct view *v, *last = NULL;
		wl_list_for_each(v, &s->views, link) {
			if (v->mapped && !v->minimized && v->ws == s->cur_ws) {
				last = v;
			}
		}
		if (last) {
			focus_view(last);
		}
		return true;
	}
	if (sym == XKB_KEY_Print) {
		send_action(s, "screenshot");
		return true;
	}
	if (!super) {
		return false;
	}
	/* digits on any layout: map keysyms of the number row */
	int digit = -1;
	switch (sym) {
	case XKB_KEY_1: case XKB_KEY_exclam: digit = 1; break;
	case XKB_KEY_2: case XKB_KEY_at: case XKB_KEY_quotedbl: digit = 2; break;
	case XKB_KEY_3: case XKB_KEY_numbersign: case XKB_KEY_section: digit = 3; break;
	case XKB_KEY_4: case XKB_KEY_dollar: digit = 4; break;
	case XKB_KEY_5: case XKB_KEY_percent: digit = 5; break;
	case XKB_KEY_6: case XKB_KEY_asciicircum: case XKB_KEY_ampersand: digit = 6; break;
	case XKB_KEY_7: case XKB_KEY_slash: digit = 7; break;
	case XKB_KEY_8: case XKB_KEY_asterisk: case XKB_KEY_parenleft: digit = 8; break;
	case XKB_KEY_9: case XKB_KEY_parenright: digit = 9; break;
	case XKB_KEY_0: case XKB_KEY_equal: digit = 10; break;
	}
	if (digit > 0) {
		if (shift && focused) {
			view_to_workspace(focused, digit - 1);
		} else {
			switch_workspace(s, digit - 1);
		}
		return true;
	}
	switch (sym) {
	case XKB_KEY_space:
		send_action(s, "launcher");
		return true;
	case XKB_KEY_Return:
		send_action(s, "terminal");
		return true;
	case XKB_KEY_e:
		send_action(s, "files");
		return true;
	case XKB_KEY_comma:
		send_action(s, "settings");
		return true;
	case XKB_KEY_l:
		send_action(s, "lock");
		return true;
	case XKB_KEY_a:
		send_action(s, "control");
		return true;
	case XKB_KEY_d:
		ipc_handle(&(struct ipc_client){.server = s}, (char[]){"show_desktop"});
		return true;
	case XKB_KEY_q:
		if (focused) view_close(focused);
		return true;
	case XKB_KEY_f:
		if (focused) view_fullscreen(focused, !focused->fullscreen);
		return true;
	case XKB_KEY_m:
		if (focused) view_minimize(focused, true);
		return true;
	case XKB_KEY_Up:
		if (focused) view_maximize(focused, true);
		return true;
	case XKB_KEY_Down:
		if (focused) view_maximize(focused, false);
		return true;
	case XKB_KEY_Left:
	case XKB_KEY_Right: {
		int dir = sym == XKB_KEY_Left ? -1 : 1;
		int target = (s->cur_ws + dir + s->n_ws) % s->n_ws;
		if (shift && focused) {
			view_to_workspace(focused, target);
		}
		if (ctrl || shift) {
			switch_workspace(s, target);
		}
		return ctrl || shift;
	}
	case XKB_KEY_E:
		if (shift) {
			wl_display_terminate(s->display);
			return true;
		}
		break;
	case XKB_KEY_Escape:
		if (shift) {
			wl_display_terminate(s->display);
			return true;
		}
		break;
	}
	return false;
}

static void keyboard_modifiers(struct wl_listener *l, void *data) {
	struct keyboard *k = wl_container_of(l, k, modifiers);
	wlr_seat_set_keyboard(k->server->seat, k->wlr_keyboard);
	wlr_seat_keyboard_notify_modifiers(k->server->seat, &k->wlr_keyboard->modifiers);
}

static void keyboard_key(struct wl_listener *l, void *data) {
	struct keyboard *k = wl_container_of(l, k, key);
	struct server *s = k->server;
	struct wlr_keyboard_key_event *ev = data;
	uint32_t keycode = ev->keycode + 8;
	const xkb_keysym_t *syms;
	int nsyms = xkb_state_key_get_syms(k->wlr_keyboard->xkb_state, keycode, &syms);
	uint32_t mods = wlr_keyboard_get_modifiers(k->wlr_keyboard);
	bool handled = false;
	if (ev->state == WL_KEYBOARD_KEY_STATE_PRESSED) {
		for (int i = 0; i < nsyms; i++) {
			handled = handle_keybinding(s, syms[i], mods);
			if (handled) break;
		}
	}
	if (!handled) {
		wlr_seat_set_keyboard(s->seat, k->wlr_keyboard);
		wlr_seat_keyboard_notify_key(s->seat, ev->time_msec, ev->keycode, ev->state);
	}
}

static void keyboard_destroy(struct wl_listener *l, void *data) {
	struct keyboard *k = wl_container_of(l, k, destroy);
	wl_list_remove(&k->modifiers.link);
	wl_list_remove(&k->key.link);
	wl_list_remove(&k->destroy.link);
	wl_list_remove(&k->link);
	free(k);
}

static void new_keyboard(struct server *s, struct wlr_input_device *dev) {
	struct wlr_keyboard *wk = wlr_keyboard_from_input_device(dev);
	struct keyboard *k = calloc(1, sizeof(*k));
	k->server = s;
	k->wlr_keyboard = wk;
	wl_list_insert(&s->keyboards, &k->link);
	apply_keymap(s);
	if (!wk->keymap) {
		struct xkb_context *ctx = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
		struct xkb_keymap *km = xkb_keymap_new_from_names(ctx, NULL,
			XKB_KEYMAP_COMPILE_NO_FLAGS);
		wlr_keyboard_set_keymap(wk, km);
		xkb_keymap_unref(km);
		xkb_context_unref(ctx);
	}
	wlr_keyboard_set_repeat_info(wk, 30, 300);
	k->modifiers.notify = keyboard_modifiers;
	wl_signal_add(&wk->events.modifiers, &k->modifiers);
	k->key.notify = keyboard_key;
	wl_signal_add(&wk->events.key, &k->key);
	k->destroy.notify = keyboard_destroy;
	wl_signal_add(&dev->events.destroy, &k->destroy);
	wlr_seat_set_keyboard(s->seat, wk);
}

static void server_new_input(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, new_input);
	struct wlr_input_device *dev = data;
	switch (dev->type) {
	case WLR_INPUT_DEVICE_KEYBOARD:
		new_keyboard(s, dev);
		break;
	case WLR_INPUT_DEVICE_POINTER:
		wlr_cursor_attach_input_device(s->cursor, dev);
		break;
	case WLR_INPUT_DEVICE_TOUCH:
		wlr_cursor_attach_input_device(s->cursor, dev);
		s->n_touch++;
		break;
	case WLR_INPUT_DEVICE_TABLET: {
		wlr_cursor_attach_input_device(s->cursor, dev);
		struct wlr_tablet *tablet = wlr_tablet_from_input_device(dev);
		tablet->data = wlr_tablet_create(s->tablet_mgr, s->seat, dev);
		break;
	}
	default:
		break;
	}
	uint32_t caps = WL_SEAT_CAPABILITY_POINTER;
	if (!wl_list_empty(&s->keyboards)) {
		caps |= WL_SEAT_CAPABILITY_KEYBOARD;
	}
	if (s->n_touch > 0) {
		caps |= WL_SEAT_CAPABILITY_TOUCH;
	}
	wlr_seat_set_capabilities(s->seat, caps);
}

/* ------------------------------------------------------------------ */
/* pointer                                                            */

/* Find what is under the cursor. Returns the surface (if any) and fills
 * in the owning view / layer, plus which decoration rect was hit. */
static struct wlr_surface *desktop_at(struct server *s, double lx, double ly,
		double *sx, double *sy, struct view **view_out, struct layer **layer_out,
		struct wlr_scene_node **hit_node) {
	*view_out = NULL;
	*layer_out = NULL;
	/* the drag icon sits right under the cursor; never hit-test it */
	wlr_scene_node_set_enabled(&s->layers[LYR_DRAG]->node, false);
	struct wlr_scene_node *node = wlr_scene_node_at(&s->scene->tree.node, lx, ly, sx, sy);
	wlr_scene_node_set_enabled(&s->layers[LYR_DRAG]->node, true);
	if (hit_node) {
		*hit_node = node;
	}
	if (!node) {
		return NULL;
	}
	struct wlr_surface *surface = NULL;
	if (node->type == WLR_SCENE_NODE_BUFFER) {
		struct wlr_scene_surface *ss =
			wlr_scene_surface_try_from_buffer(wlr_scene_buffer_from_node(node));
		if (ss) {
			surface = ss->surface;
		}
	}
	for (struct wlr_scene_tree *t = node->parent; t; t = t->node.parent) {
		enum node_kind *kind = t->node.data;
		if (!kind) {
			continue;
		}
		if (*kind == NODE_VIEW) {
			*view_out = (struct view *)kind;
		} else if (*kind == NODE_LAYER) {
			*layer_out = (struct layer *)kind;
		}
		break;
	}
	return surface;
}

static void reset_cursor_mode(struct server *s) {
	s->cursor_mode = CUR_PASSTHROUGH;
	s->grabbed = NULL;
}

static void process_motion(struct server *s, uint32_t time) {
	if (s->drag_icon) {
		wlr_scene_node_set_position(&s->drag_icon->node, s->cursor->x, s->cursor->y);
	}
	if (s->cursor_mode == CUR_MOVE && s->grabbed) {
		struct view *v = s->grabbed;
		if (v->maximized) {
			/* drag out of maximized: restore under the cursor */
			struct wlr_box g = view_geometry(v);
			view_maximize(v, false);
			s->grab_x = g.width > 0 ? v->saved.width / 2.0 : 0;
			s->grab_y = 10;
		}
		view_move(v, s->cursor->x - s->grab_x, s->cursor->y - s->grab_y);
		return;
	}
	if (s->cursor_mode == CUR_RESIZE && s->grabbed) {
		struct view *v = s->grabbed;
		double bx = s->cursor->x - s->grab_x;
		double by = s->cursor->y - s->grab_y;
		int left = s->grab_box.x, right = s->grab_box.x + s->grab_box.width;
		int top = s->grab_box.y, bottom = s->grab_box.y + s->grab_box.height;
		if (s->resize_edges & WLR_EDGE_TOP) {
			top = by;
			if (top >= bottom) top = bottom - 1;
		} else if (s->resize_edges & WLR_EDGE_BOTTOM) {
			bottom = by;
			if (bottom <= top) bottom = top + 1;
		}
		if (s->resize_edges & WLR_EDGE_LEFT) {
			left = bx;
			if (left >= right) left = right - 1;
		} else if (s->resize_edges & WLR_EDGE_RIGHT) {
			right = bx;
			if (right <= left) right = left + 1;
		}
		view_configure(v, left, top, right - left, bottom - top);
		return;
	}

	double sx, sy;
	struct view *v;
	struct layer *ly;
	struct wlr_surface *surface = desktop_at(s, s->cursor->x, s->cursor->y,
		&sx, &sy, &v, &ly, NULL);
	if (!surface) {
		wlr_cursor_set_xcursor(s->cursor, s->xcursor_mgr, "default");
	}
	if (surface) {
		wlr_seat_pointer_notify_enter(s->seat, surface, sx, sy);
		wlr_seat_pointer_notify_motion(s->seat, time, sx, sy);
	} else {
		wlr_seat_pointer_clear_focus(s->seat);
	}
}

static void cursor_motion(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, cursor_motion);
	struct wlr_pointer_motion_event *ev = data;
	wlr_relative_pointer_manager_v1_send_relative_motion(s->relative_pointer, s->seat,
		(uint64_t)ev->time_msec * 1000, ev->delta_x, ev->delta_y,
		ev->unaccel_dx, ev->unaccel_dy);
	wlr_cursor_move(s->cursor, &ev->pointer->base, ev->delta_x, ev->delta_y);
	process_motion(s, ev->time_msec);
}

static void cursor_motion_abs(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, cursor_motion_abs);
	struct wlr_pointer_motion_absolute_event *ev = data;
	wlr_cursor_warp_absolute(s->cursor, &ev->pointer->base, ev->x, ev->y);
	process_motion(s, ev->time_msec);
}

static void begin_interactive(struct view *v, enum cursor_mode mode, uint32_t edges) {
	struct server *s = v->server;
	if (v->fullscreen) {
		return;
	}
	s->grabbed = v;
	s->cursor_mode = mode;
	if (mode == CUR_MOVE) {
		s->grab_x = s->cursor->x - v->x;
		s->grab_y = s->cursor->y - v->y;
	} else {
		struct wlr_box g = view_geometry(v);
		double bx = v->x + ((edges & WLR_EDGE_RIGHT) ? g.width : 0);
		double by = v->y + ((edges & WLR_EDGE_BOTTOM) ? g.height : 0);
		s->grab_x = s->cursor->x - bx;
		s->grab_y = s->cursor->y - by;
		s->grab_box = (struct wlr_box){v->x, v->y, g.width, g.height};
		s->resize_edges = edges;
		if (v->maximized) {
			v->maximized = false;
			if (v->type == VIEW_XDG) wlr_xdg_toplevel_set_maximized(v->xdg, false);
		}
	}
}

static void focus_layer(struct server *s, struct layer *ly) {
	if (s->locked) {
		return;
	}
	s->focused_layer = ly;
	keyboard_enter(s, ly->surface->surface);
}

static void cursor_button(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, cursor_button);
	struct wlr_pointer_button_event *ev = data;

	if (ev->state == WL_POINTER_BUTTON_STATE_RELEASED) {
		if (s->cursor_mode != CUR_PASSTHROUGH) {
			struct view *g = s->grabbed;
			reset_cursor_mode(s);
			if (g && g->type == VIEW_XDG) {
				wlr_xdg_toplevel_set_resizing(g->xdg, false);
			}
		}
		wlr_seat_pointer_notify_button(s->seat, ev->time_msec, ev->button, ev->state);
		return;
	}

	double sx, sy;
	struct view *v;
	struct layer *ly;
	struct wlr_scene_node *hit;
	struct wlr_surface *surface = desktop_at(s, s->cursor->x, s->cursor->y,
		&sx, &sy, &v, &ly, &hit);
	struct wlr_keyboard *kb = wlr_seat_get_keyboard(s->seat);
	uint32_t mods = kb ? wlr_keyboard_get_modifiers(kb) : 0;

	if (s->locked) {
		wlr_seat_pointer_notify_button(s->seat, ev->time_msec, ev->button, ev->state);
		return;
	}
	if (v) {
		/* clicking a window dismisses an on-demand layer focus */
		if (s->focused_layer && s->focused_layer->surface->current.keyboard_interactive !=
				ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_EXCLUSIVE) {
			s->focused_layer = NULL;
		}
		focus_view(v);
		if (mods & WLR_MODIFIER_LOGO) {
			if (ev->button == BTN_LEFT) {
				begin_interactive(v, CUR_MOVE, 0);
			} else if (ev->button == BTN_RIGHT) {
				struct wlr_box g = view_geometry(v);
				uint32_t edges = 0;
				edges |= (s->cursor->x < v->x + g.width / 2.0) ? WLR_EDGE_LEFT : WLR_EDGE_RIGHT;
				edges |= (s->cursor->y < v->y + g.height / 2.0) ? WLR_EDGE_TOP : WLR_EDGE_BOTTOM;
				begin_interactive(v, CUR_RESIZE, edges);
			}
			return;
		}
		if (!surface && hit && v->ssd) {
			if (hit == &v->btn_close->node) {
				view_close(v);
			} else if (hit == &v->btn_min->node) {
				view_minimize(v, true);
			} else if (hit == &v->btn_max->node) {
				view_maximize(v, !v->maximized);
			} else {
				begin_interactive(v, CUR_MOVE, 0);
			}
			return;
		}
	} else if (ly && ly->surface->current.keyboard_interactive !=
			ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_NONE) {
		focus_layer(s, ly);
	} else if (!surface) {
		/* clicked on nothing */
	}
	wlr_seat_pointer_notify_button(s->seat, ev->time_msec, ev->button, ev->state);
}

static void cursor_axis(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, cursor_axis);
	struct wlr_pointer_axis_event *ev = data;
	wlr_seat_pointer_notify_axis(s->seat, ev->time_msec, ev->orientation, ev->delta,
		ev->delta_discrete, ev->source, ev->relative_direction);
}

static void cursor_frame(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, cursor_frame);
	wlr_seat_pointer_notify_frame(s->seat);
}

static void seat_request_cursor(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, request_cursor);
	struct wlr_seat_pointer_request_set_cursor_event *ev = data;
	if (s->seat->pointer_state.focused_client == ev->seat_client) {
		wlr_cursor_set_surface(s->cursor, ev->surface, ev->hotspot_x, ev->hotspot_y);
	}
}

static void request_set_shape(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, request_set_shape);
	struct wlr_cursor_shape_manager_v1_request_set_shape_event *ev = data;
	if (s->seat->pointer_state.focused_client == ev->seat_client) {
		wlr_cursor_set_xcursor(s->cursor, s->xcursor_mgr, wlr_cursor_shape_v1_name(ev->shape));
	}
}

static void seat_request_start_drag(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, request_start_drag);
	struct wlr_seat_request_start_drag_event *ev = data;
	if (wlr_seat_validate_pointer_grab_serial(s->seat, ev->origin, ev->serial)) {
		wlr_seat_start_pointer_drag(s->seat, ev->drag, ev->serial);
	} else {
		wlr_data_source_destroy(ev->drag->source);
	}
}

static void drag_destroy(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, drag_destroy);
	wl_list_remove(&s->drag_destroy.link);
	/* the scene drag icon tree goes away together with the icon */
	s->drag_icon = NULL;
	/* the surface under the cursor did not see the motion during the drag */
	process_motion(s, 0);
}

static void seat_start_drag(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, start_drag);
	struct wlr_drag *drag = data;
	if (drag->icon) {
		s->drag_icon = wlr_scene_drag_icon_create(s->layers[LYR_DRAG], drag->icon);
		wlr_scene_node_set_position(&s->drag_icon->node, s->cursor->x, s->cursor->y);
	}
	s->drag_destroy.notify = drag_destroy;
	wl_signal_add(&drag->events.destroy, &s->drag_destroy);
}

static void seat_request_set_selection(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, request_set_selection);
	struct wlr_seat_request_set_selection_event *ev = data;
	wlr_seat_set_selection(s->seat, ev->source, ev->serial);
}

static void seat_request_set_primary(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, request_set_primary);
	struct wlr_seat_request_set_primary_selection_event *ev = data;
	wlr_seat_set_primary_selection(s->seat, ev->source, ev->serial);
}

/* ------------------------------------------------------------------ */
/* touch                                                              */

static struct touch_point *touch_point_find(struct server *s, int32_t id) {
	for (int i = 0; i < MAX_TOUCH_POINTS; i++) {
		if (s->touch_points[i].active && s->touch_points[i].id == id) {
			return &s->touch_points[i];
		}
	}
	return NULL;
}

static struct touch_point *touch_point_new(struct server *s, int32_t id) {
	for (int i = 0; i < MAX_TOUCH_POINTS; i++) {
		if (!s->touch_points[i].active) {
			s->touch_points[i] = (struct touch_point){.active = true, .id = id};
			return &s->touch_points[i];
		}
	}
	return NULL;
}

static void touch_down(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, touch_down);
	struct wlr_touch_down_event *ev = data;
	double lx, ly;
	wlr_cursor_absolute_to_layout_coords(s->cursor, &ev->touch->base, ev->x, ev->y, &lx, &ly);
	double sx, sy;
	struct view *v;
	struct layer *ly2;
	struct wlr_surface *surface = desktop_at(s, lx, ly, &sx, &sy, &v, &ly2, NULL);
	struct touch_point *tp = touch_point_new(s, ev->touch_id);
	if (!tp) {
		return;
	}
	tp->surface = surface;
	tp->ox = lx - sx;
	tp->oy = ly - sy;
	if (s->locked) {
		if (surface) {
			wlr_seat_touch_notify_down(s->seat, surface, ev->time_msec, ev->touch_id, sx, sy);
		}
		return;
	}
	if (v) {
		if (s->focused_layer && s->focused_layer->surface->current.keyboard_interactive !=
				ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_EXCLUSIVE) {
			s->focused_layer = NULL;
		}
		focus_view(v);
	} else if (ly2 && ly2->surface->current.keyboard_interactive !=
			ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_NONE) {
		focus_layer(s, ly2);
	}
	if (surface) {
		wlr_seat_touch_notify_down(s->seat, surface, ev->time_msec, ev->touch_id, sx, sy);
	}
}

static void touch_up(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, touch_up);
	struct wlr_touch_up_event *ev = data;
	struct touch_point *tp = touch_point_find(s, ev->touch_id);
	if (tp) {
		if (tp->surface) {
			wlr_seat_touch_notify_up(s->seat, ev->time_msec, ev->touch_id);
		}
		tp->active = false;
	}
}

static void touch_motion(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, touch_motion);
	struct wlr_touch_motion_event *ev = data;
	struct touch_point *tp = touch_point_find(s, ev->touch_id);
	if (!tp || !tp->surface) {
		return;
	}
	double lx, ly;
	wlr_cursor_absolute_to_layout_coords(s->cursor, &ev->touch->base, ev->x, ev->y, &lx, &ly);
	wlr_seat_touch_notify_motion(s->seat, ev->time_msec, ev->touch_id, lx - tp->ox, ly - tp->oy);
}

static void touch_cancel(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, touch_cancel);
	struct wlr_touch_cancel_event *ev = data;
	struct wlr_touch_point *point = wlr_seat_touch_get_point(s->seat, ev->touch_id);
	if (point && point->client) {
		wlr_seat_touch_notify_cancel(s->seat, point->client);
	}
	struct touch_point *tp = touch_point_find(s, ev->touch_id);
	if (tp) {
		tp->active = false;
	}
}

static void touch_frame(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, touch_frame);
	wlr_seat_touch_notify_frame(s->seat);
}

/* ------------------------------------------------------------------ */
/* tablet tool (pen / stylus)                                        */

static struct wlr_tablet_v2_tablet_tool *tablet_tool_v2(struct server *s,
		struct wlr_tablet_tool *tool) {
	if (!tool->data) {
		tool->data = wlr_tablet_tool_create(s->tablet_mgr, s->seat, tool);
	}
	return tool->data;
}

/* true if the surface under the tool wants native tablet-v2 events; if not,
 * we emulate a regular pointer so plain apps can still be used with the pen */
static bool tablet_focus(struct server *s, struct wlr_tablet_v2_tablet *tablet,
		double tx, double ty, struct wlr_surface **surface_out,
		double *sx_out, double *sy_out) {
	double sx, sy;
	struct view *v;
	struct layer *ly;
	struct wlr_surface *surface = desktop_at(s, tx, ty, &sx, &sy, &v, &ly, NULL);
	*surface_out = surface;
	*sx_out = sx;
	*sy_out = sy;
	return surface && tablet && wlr_surface_accepts_tablet_v2(surface, tablet);
}

static void tablet_tool_proximity(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, tablet_tool_proximity);
	struct wlr_tablet_tool_proximity_event *ev = data;
	struct wlr_tablet_v2_tablet *tablet = ev->tablet->data;
	struct wlr_tablet_v2_tablet_tool *tool = tablet_tool_v2(s, ev->tool);
	if (ev->state == WLR_TABLET_TOOL_PROXIMITY_OUT) {
		if (tool) {
			wlr_tablet_v2_tablet_tool_notify_proximity_out(tool);
		}
		return;
	}
	wlr_cursor_warp_absolute(s->cursor, &ev->tablet->base, ev->x, ev->y);
	process_motion(s, ev->time_msec);
	struct wlr_surface *surface;
	double sx, sy;
	if (tablet_focus(s, tablet, s->cursor->x, s->cursor->y, &surface, &sx, &sy) && tool) {
		wlr_tablet_v2_tablet_tool_notify_proximity_in(tool, tablet, surface);
		wlr_tablet_v2_tablet_tool_notify_motion(tool, sx, sy);
	}
}

static void tablet_tool_axis(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, tablet_tool_axis);
	struct wlr_tablet_tool_axis_event *ev = data;
	struct wlr_tablet_v2_tablet *tablet = ev->tablet->data;
	struct wlr_tablet_v2_tablet_tool *tool = tablet_tool_v2(s, ev->tool);
	if (ev->updated_axes & (WLR_TABLET_TOOL_AXIS_X | WLR_TABLET_TOOL_AXIS_Y)) {
		wlr_cursor_warp_absolute(s->cursor, &ev->tablet->base, ev->x, ev->y);
		process_motion(s, ev->time_msec);
	}
	struct wlr_surface *surface;
	double sx, sy;
	bool accepts = tablet_focus(s, tablet, s->cursor->x, s->cursor->y, &surface, &sx, &sy);
	if (!accepts || !tool) {
		return;
	}
	if (ev->updated_axes & (WLR_TABLET_TOOL_AXIS_X | WLR_TABLET_TOOL_AXIS_Y)) {
		wlr_tablet_v2_tablet_tool_notify_motion(tool, sx, sy);
	}
	if (ev->updated_axes & WLR_TABLET_TOOL_AXIS_PRESSURE) {
		wlr_tablet_v2_tablet_tool_notify_pressure(tool, ev->pressure);
	}
	if (ev->updated_axes & WLR_TABLET_TOOL_AXIS_DISTANCE) {
		wlr_tablet_v2_tablet_tool_notify_distance(tool, ev->distance);
	}
	if (ev->updated_axes & (WLR_TABLET_TOOL_AXIS_TILT_X | WLR_TABLET_TOOL_AXIS_TILT_Y)) {
		wlr_tablet_v2_tablet_tool_notify_tilt(tool, ev->tilt_x, ev->tilt_y);
	}
	if (ev->updated_axes & WLR_TABLET_TOOL_AXIS_ROTATION) {
		wlr_tablet_v2_tablet_tool_notify_rotation(tool, ev->rotation);
	}
}

static void tablet_tool_tip(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, tablet_tool_tip);
	struct wlr_tablet_tool_tip_event *ev = data;
	struct wlr_tablet_v2_tablet *tablet = ev->tablet->data;
	struct wlr_tablet_v2_tablet_tool *tool = tablet_tool_v2(s, ev->tool);

	double sx, sy;
	struct view *v;
	struct layer *ly;
	struct wlr_surface *surface = desktop_at(s, s->cursor->x, s->cursor->y, &sx, &sy, &v, &ly, NULL);
	bool accepts = surface && tablet && wlr_surface_accepts_tablet_v2(surface, tablet);
	bool down = ev->state == WLR_TABLET_TOOL_TIP_DOWN;

	if (down && !s->locked) {
		if (v) {
			if (s->focused_layer && s->focused_layer->surface->current.keyboard_interactive !=
					ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_EXCLUSIVE) {
				s->focused_layer = NULL;
			}
			focus_view(v);
		} else if (ly && ly->surface->current.keyboard_interactive !=
				ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_NONE) {
			focus_layer(s, ly);
		}
	}

	if (accepts && tool) {
		if (down) {
			wlr_tablet_v2_tablet_tool_notify_down(tool);
		} else {
			wlr_tablet_v2_tablet_tool_notify_up(tool);
		}
		return;
	}
	/* app has no tablet-v2 support: emulate a left click so it still works */
	wlr_seat_pointer_notify_button(s->seat, ev->time_msec, BTN_LEFT,
		down ? WL_POINTER_BUTTON_STATE_PRESSED : WL_POINTER_BUTTON_STATE_RELEASED);
	wlr_seat_pointer_notify_frame(s->seat);
}

static void tablet_tool_button(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, tablet_tool_button);
	struct wlr_tablet_tool_button_event *ev = data;
	struct wlr_tablet_v2_tablet *tablet = ev->tablet->data;
	struct wlr_tablet_v2_tablet_tool *tool = tablet_tool_v2(s, ev->tool);
	struct wlr_surface *surface;
	double sx, sy;
	if (tablet_focus(s, tablet, s->cursor->x, s->cursor->y, &surface, &sx, &sy) && tool) {
		wlr_tablet_v2_tablet_tool_notify_button(tool, ev->button,
			ev->state == WLR_BUTTON_PRESSED ? ZWP_TABLET_PAD_V2_BUTTON_STATE_PRESSED :
				ZWP_TABLET_PAD_V2_BUTTON_STATE_RELEASED);
	}
}

/* ------------------------------------------------------------------ */
/* layer shell                                                        */

static void arrange_layers(struct output *out) {
	struct server *s = out->server;
	struct wlr_box full = out->full;
	struct wlr_box usable = full;
	/* exclusive surfaces first so the others see the reduced area */
	for (int pass = 0; pass < 2; pass++) {
		struct layer *ly;
		wl_list_for_each(ly, &s->layers_list, link) {
			if (ly->output != out || !ly->surface->initialized) {
				continue;
			}
			bool excl = ly->surface->current.exclusive_zone > 0;
			if (excl != (pass == 0)) {
				continue;
			}
			wlr_scene_layer_surface_v1_configure(ly->scene, &full, &usable);
			wlr_scene_node_set_position(&ly->popups->node,
				ly->scene->tree->node.x, ly->scene->tree->node.y);
		}
	}
	bool changed = memcmp(&usable, &out->usable, sizeof(usable)) != 0;
	out->usable = usable;
	if (changed) {
		struct view *v;
		wl_list_for_each(v, &s->views, link) {
			if (v->maximized && view_output(v) == out) {
				int top = view_top_offset(v);
				view_configure(v, usable.x, usable.y + top,
					usable.width, usable.height - top);
			}
		}
	}
}

static struct wlr_scene_tree *layer_tree(struct server *s, enum zwlr_layer_shell_v1_layer l) {
	switch (l) {
	case ZWLR_LAYER_SHELL_V1_LAYER_BACKGROUND: return s->layers[LYR_BACKGROUND];
	case ZWLR_LAYER_SHELL_V1_LAYER_BOTTOM: return s->layers[LYR_BOTTOM];
	case ZWLR_LAYER_SHELL_V1_LAYER_TOP: return s->layers[LYR_TOP];
	case ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY: return s->layers[LYR_OVERLAY];
	}
	return s->layers[LYR_TOP];
}

static void layer_commit(struct wl_listener *l, void *data) {
	struct layer *ly = wl_container_of(l, ly, commit);
	struct wlr_layer_surface_v1 *ls = ly->surface;
	if (!ly->output) {
		return;
	}
	if (ls->current.committed & WLR_LAYER_SURFACE_V1_STATE_LAYER) {
		struct wlr_scene_tree *t = layer_tree(ly->server, ls->current.layer);
		wlr_scene_node_reparent(&ly->scene->tree->node, t);
		/* keep popups above everything in the same band */
		wlr_scene_node_reparent(&ly->popups->node,
			ls->current.layer < ZWLR_LAYER_SHELL_V1_LAYER_TOP ?
			ly->server->layers[LYR_TOP] : t);
	}
	if (ls->initial_commit || ls->current.committed) {
		arrange_layers(ly->output);
	}
}

static void layer_map(struct wl_listener *l, void *data) {
	struct layer *ly = wl_container_of(l, ly, map);
	struct server *s = ly->server;
	ly->mapped = true;
	arrange_layers(ly->output);
	if (ly->surface->current.keyboard_interactive ==
			ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_EXCLUSIVE &&
			ly->surface->current.layer >= ZWLR_LAYER_SHELL_V1_LAYER_TOP) {
		focus_layer(s, ly);
	}
}

static void layer_unmap(struct wl_listener *l, void *data) {
	struct layer *ly = wl_container_of(l, ly, unmap);
	struct server *s = ly->server;
	ly->mapped = false;
	if (s->focused_layer == ly) {
		s->focused_layer = NULL;
		focus_top_view(s);
	}
	if (ly->output) {
		arrange_layers(ly->output);
	}
}

static void layer_destroy(struct wl_listener *l, void *data) {
	struct layer *ly = wl_container_of(l, ly, destroy);
	struct server *s = ly->server;
	if (s->focused_layer == ly) {
		s->focused_layer = NULL;
		focus_top_view(s);
	}
	wl_list_remove(&ly->map.link);
	wl_list_remove(&ly->unmap.link);
	wl_list_remove(&ly->commit.link);
	wl_list_remove(&ly->destroy.link);
	wl_list_remove(&ly->new_popup.link);
	wl_list_remove(&ly->link);
	wlr_scene_node_destroy(&ly->popups->node);
	struct output *out = ly->output;
	free(ly);
	if (out) {
		arrange_layers(out);
	}
}

static void layer_new_popup(struct wl_listener *l, void *data) {
	struct layer *ly = wl_container_of(l, ly, new_popup);
	struct wlr_xdg_popup *popup = data;
	struct wlr_scene_tree *t = wlr_scene_xdg_surface_create(ly->popups, popup->base);
	popup->base->data = t;
}

static void server_new_layer(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, new_layer);
	struct wlr_layer_surface_v1 *ls = data;
	struct output *out = NULL;
	if (ls->output) {
		struct output *o;
		wl_list_for_each(o, &s->outputs, link) {
			if (o->wlr_output == ls->output) out = o;
		}
	}
	if (!out) {
		out = output_at(s, s->cursor->x, s->cursor->y);
	}
	if (!out) {
		wlr_layer_surface_v1_destroy(ls);
		return;
	}
	ls->output = out->wlr_output;
	struct layer *ly = calloc(1, sizeof(*ly));
	ly->kind = NODE_LAYER;
	ly->server = s;
	ly->surface = ls;
	ly->output = out;
	ly->scene = wlr_scene_layer_surface_v1_create(layer_tree(s, ls->pending.layer), ls);
	ly->scene->tree->node.data = ly;
	ly->popups = wlr_scene_tree_create(ls->pending.layer < ZWLR_LAYER_SHELL_V1_LAYER_TOP ?
		s->layers[LYR_TOP] : layer_tree(s, ls->pending.layer));
	ly->popups->node.data = ly;
	ls->data = ly;

	ly->map.notify = layer_map;
	wl_signal_add(&ls->surface->events.map, &ly->map);
	ly->unmap.notify = layer_unmap;
	wl_signal_add(&ls->surface->events.unmap, &ly->unmap);
	ly->commit.notify = layer_commit;
	wl_signal_add(&ls->surface->events.commit, &ly->commit);
	ly->destroy.notify = layer_destroy;
	wl_signal_add(&ls->events.destroy, &ly->destroy);
	ly->new_popup.notify = layer_new_popup;
	wl_signal_add(&ls->events.new_popup, &ly->new_popup);
	wl_list_insert(&s->layers_list, &ly->link);
}

/* ------------------------------------------------------------------ */
/* xdg shell                                                          */

static void xdg_map(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, map);
	struct server *s = v->server;
	v->mapped = true;
	v->ws = s->cur_ws;
	if (!v->placed && !v->maximized && !v->fullscreen) {
		view_place(v);
	}
	view_set_visible(v);
	focus_view(v);
	schedule_state(s);
}

static void view_unmap_common(struct view *v) {
	struct server *s = v->server;
	v->mapped = false;
	wlr_scene_node_set_enabled(&v->tree->node, false);
	if (s->grabbed == v) {
		reset_cursor_mode(s);
	}
	if (view_from_surface(s, s->seat->keyboard_state.focused_surface) == v) {
		wlr_seat_keyboard_notify_clear_focus(s->seat);
	}
	focus_top_view(s);
	schedule_state(s);
}

static void xdg_unmap(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, unmap);
	view_unmap_common(v);
}

static void xdg_commit(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, commit);
	struct wlr_xdg_surface *base = v->xdg->base;
	if (base->initial_commit) {
		wlr_xdg_toplevel_set_wm_capabilities(v->xdg,
			WLR_XDG_TOPLEVEL_WM_CAPABILITIES_MAXIMIZE |
			WLR_XDG_TOPLEVEL_WM_CAPABILITIES_FULLSCREEN |
			WLR_XDG_TOPLEVEL_WM_CAPABILITIES_MINIMIZE);
		struct output *out = output_at(v->server, v->server->cursor->x, v->server->cursor->y);
		if (out) {
			wlr_xdg_toplevel_set_bounds(v->xdg, out->usable.width, out->usable.height);
		}
		wlr_xdg_toplevel_set_size(v->xdg, 0, 0);
		return;
	}
	/* the scene xdg tree already offsets by the window geometry, so
	 * v->x/v->y is the top-left of the visible window */
	struct server *s = v->server;
	if (s->grabbed == v && s->cursor_mode == CUR_RESIZE) {
		/* anchor the opposite edge while resizing from left/top */
		int right = s->grab_box.x + s->grab_box.width;
		int bottom = s->grab_box.y + s->grab_box.height;
		int nx = v->x, ny = v->y;
		if (s->resize_edges & WLR_EDGE_LEFT) nx = right - base->geometry.width;
		if (s->resize_edges & WLR_EDGE_TOP) ny = bottom - base->geometry.height;
		if (nx != v->x || ny != v->y) {
			view_move(v, nx, ny);
		}
	}
}

static void view_destroy_common(struct view *v) {
	struct server *s = v->server;
	if (s->grabbed == v) {
		reset_cursor_mode(s);
	}
	wl_list_remove(&v->link);
	wlr_scene_node_destroy(&v->tree->node);
	schedule_state(s);
	free(v);
}

static void xdg_destroy(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, destroy);
	wl_list_remove(&v->map.link);
	wl_list_remove(&v->unmap.link);
	wl_list_remove(&v->commit.link);
	wl_list_remove(&v->destroy.link);
	wl_list_remove(&v->request_move.link);
	wl_list_remove(&v->request_resize.link);
	wl_list_remove(&v->request_maximize.link);
	wl_list_remove(&v->request_fullscreen.link);
	wl_list_remove(&v->request_minimize.link);
	wl_list_remove(&v->set_title.link);
	wl_list_remove(&v->set_app_id.link);
	view_destroy_common(v);
}

static void xdg_request_move(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, request_move);
	begin_interactive(v, CUR_MOVE, 0);
}

static void xdg_request_resize(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, request_resize);
	struct wlr_xdg_toplevel_resize_event *ev = data;
	begin_interactive(v, CUR_RESIZE, ev->edges);
	wlr_xdg_toplevel_set_resizing(v->xdg, true);
}

static void xdg_request_maximize(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, request_maximize);
	if (!v->xdg->base->initialized) {
		return;
	}
	if (!v->mapped) {
		/* remember the wish, honour it on map */
		wlr_xdg_surface_schedule_configure(v->xdg->base);
		return;
	}
	view_maximize(v, v->xdg->requested.maximized);
	schedule_state(v->server);
}

static void xdg_request_fullscreen(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, request_fullscreen);
	if (!v->xdg->base->initialized) {
		return;
	}
	if (!v->mapped) {
		wlr_xdg_surface_schedule_configure(v->xdg->base);
		return;
	}
	view_fullscreen(v, v->xdg->requested.fullscreen);
}

static void xdg_request_minimize(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, request_minimize);
	if (v->mapped) {
		view_minimize(v, true);
	}
}

static void view_set_title(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, set_title);
	schedule_state(v->server);
}

static void view_set_app_id(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, set_app_id);
	schedule_state(v->server);
}

static struct view *view_create(struct server *s, enum view_type type) {
	struct view *v = calloc(1, sizeof(*v));
	v->kind = NODE_VIEW;
	v->server = s;
	v->type = type;
	v->id = s->next_id++;
	v->ws = s->cur_ws;
	v->tree = wlr_scene_tree_create(s->ws_tree[s->cur_ws]);
	v->tree->node.data = v;
	wlr_scene_node_set_enabled(&v->tree->node, false);
	wl_list_insert(&s->views, &v->link);
	return v;
}

static void server_new_xdg_toplevel(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, new_xdg_toplevel);
	struct wlr_xdg_toplevel *tl = data;
	struct view *v = view_create(s, VIEW_XDG);
	v->xdg = tl;
	v->content = wlr_scene_xdg_surface_create(v->tree, tl->base);
	tl->base->data = v->content;

	v->map.notify = xdg_map;
	wl_signal_add(&tl->base->surface->events.map, &v->map);
	v->unmap.notify = xdg_unmap;
	wl_signal_add(&tl->base->surface->events.unmap, &v->unmap);
	v->commit.notify = xdg_commit;
	wl_signal_add(&tl->base->surface->events.commit, &v->commit);
	v->destroy.notify = xdg_destroy;
	wl_signal_add(&tl->events.destroy, &v->destroy);
	v->request_move.notify = xdg_request_move;
	wl_signal_add(&tl->events.request_move, &v->request_move);
	v->request_resize.notify = xdg_request_resize;
	wl_signal_add(&tl->events.request_resize, &v->request_resize);
	v->request_maximize.notify = xdg_request_maximize;
	wl_signal_add(&tl->events.request_maximize, &v->request_maximize);
	v->request_fullscreen.notify = xdg_request_fullscreen;
	wl_signal_add(&tl->events.request_fullscreen, &v->request_fullscreen);
	v->request_minimize.notify = xdg_request_minimize;
	wl_signal_add(&tl->events.request_minimize, &v->request_minimize);
	v->set_title.notify = view_set_title;
	wl_signal_add(&tl->events.set_title, &v->set_title);
	v->set_app_id.notify = view_set_app_id;
	wl_signal_add(&tl->events.set_app_id, &v->set_app_id);
}

/* Popups: unconstrain them into the output they appear on. */
static void popup_commit(struct wl_listener *l, void *data) {
	struct popup *p = wl_container_of(l, p, commit);
	struct wlr_xdg_popup *popup = p->xdg_popup;
	if (!popup->base->initial_commit) {
		return;
	}
	struct wlr_scene_tree *parent_tree = NULL;
	struct wlr_surface *root = popup->parent;
	/* walk up to the root (toplevel or layer surface) */
	struct wlr_xdg_popup *pp;
	while (root && (pp = wlr_xdg_popup_try_from_wlr_surface(root))) {
		root = pp->parent;
	}
	struct wlr_xdg_surface *rx = root ? wlr_xdg_surface_try_from_wlr_surface(root) : NULL;
	struct wlr_layer_surface_v1 *rl = root ? wlr_layer_surface_v1_try_from_wlr_surface(root) : NULL;
	int lx = 0, ly = 0;
	bool found = false;
	if (rx && rx->data) {
		parent_tree = rx->data;
		found = wlr_scene_node_coords(&parent_tree->node, &lx, &ly);
	} else if (rl && rl->data) {
		struct layer *layer = rl->data;
		found = wlr_scene_node_coords(&layer->scene->tree->node, &lx, &ly);
	}
	if (found) {
		struct wlr_output *o = wlr_output_layout_output_at(
			((struct server *)p->xdg_popup->base->client->shell->data)->output_layout,
			lx + 1, ly + 1);
		if (o) {
			struct wlr_box box;
			wlr_output_layout_get_box(
				((struct server *)p->xdg_popup->base->client->shell->data)->output_layout,
				o, &box);
			box.x -= lx;
			box.y -= ly;
			if (rx) {
				/* toplevel coordinates are relative to the window geometry */
				box.x += rx->geometry.x;
				box.y += rx->geometry.y;
			}
			wlr_xdg_popup_unconstrain_from_box(popup, &box);
		}
	}
	wlr_xdg_surface_schedule_configure(popup->base);
}

static void popup_destroy(struct wl_listener *l, void *data) {
	struct popup *p = wl_container_of(l, p, destroy);
	wl_list_remove(&p->commit.link);
	wl_list_remove(&p->destroy.link);
	free(p);
}

static void server_new_xdg_popup(struct wl_listener *l, void *data) {
	struct wlr_xdg_popup *popup = data;
	struct popup *p = calloc(1, sizeof(*p));
	p->xdg_popup = popup;
	/* layer-shell popups get their scene node from layer_new_popup */
	struct wlr_xdg_surface *parent = popup->parent ?
		wlr_xdg_surface_try_from_wlr_surface(popup->parent) : NULL;
	if (parent && parent->data) {
		struct wlr_scene_tree *parent_tree = parent->data;
		popup->base->data = wlr_scene_xdg_surface_create(parent_tree, popup->base);
	}
	p->commit.notify = popup_commit;
	wl_signal_add(&popup->base->surface->events.commit, &p->commit);
	p->destroy.notify = popup_destroy;
	wl_signal_add(&popup->events.destroy, &p->destroy);
}

static void request_activate(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, request_activate);
	struct wlr_xdg_activation_v1_request_activate_event *ev = data;
	struct view *v = view_from_surface(s, ev->surface);
	if (v && v->mapped) {
		focus_view(v);
	}
}

/* ------------------------------------------------------------------ */
/* XWayland                                                           */

static void x11_map(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, map);
	struct server *s = v->server;
	struct wlr_xwayland_surface *xs = v->xsurface;
	v->content = wlr_scene_subsurface_tree_create(v->tree, xs->surface);
	v->ssd = xs->decorations == WLR_XWAYLAND_SURFACE_DECORATIONS_ALL;
	if (!v->deco) {
		deco_create(v);
	}
	deco_update(v);
	v->mapped = true;
	v->ws = s->cur_ws;
	wlr_scene_node_reparent(&v->tree->node, v->fullscreen ?
		s->layers[LYR_FULLSCREEN] : s->ws_tree[v->ws]);
	if (xs->fullscreen) {
		v->placed = true;
		view_move(v, xs->x, xs->y);
		view_fullscreen(v, true);
	} else if (!v->placed) {
		view_place(v);
	} else {
		view_move(v, xs->x, xs->y);
	}
	view_set_visible(v);
	focus_view(v);
	schedule_state(s);
}

static void x11_unmap(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, unmap);
	if (v->content) {
		wlr_scene_node_destroy(&v->content->node);
		v->content = NULL;
	}
	v->placed = false;
	view_unmap_common(v);
}

static void x11_associate(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, associate);
	v->map.notify = x11_map;
	wl_signal_add(&v->xsurface->surface->events.map, &v->map);
	v->unmap.notify = x11_unmap;
	wl_signal_add(&v->xsurface->surface->events.unmap, &v->unmap);
}

static void x11_dissociate(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, dissociate);
	wl_list_remove(&v->map.link);
	wl_list_remove(&v->unmap.link);
}

static void x11_destroy(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, destroy);
	wl_list_remove(&v->associate.link);
	wl_list_remove(&v->dissociate.link);
	wl_list_remove(&v->destroy.link);
	wl_list_remove(&v->request_configure.link);
	wl_list_remove(&v->request_activate.link);
	wl_list_remove(&v->request_move.link);
	wl_list_remove(&v->request_resize.link);
	wl_list_remove(&v->request_maximize.link);
	wl_list_remove(&v->request_fullscreen.link);
	wl_list_remove(&v->request_minimize.link);
	wl_list_remove(&v->set_title.link);
	wl_list_remove(&v->set_app_id.link);
	wl_list_remove(&v->set_decorations.link);
	view_destroy_common(v);
}

static void x11_request_configure(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, request_configure);
	struct wlr_xwayland_surface_configure_event *ev = data;
	if (!v->mapped) {
		wlr_xwayland_surface_configure(v->xsurface, ev->x, ev->y, ev->width, ev->height);
		return;
	}
	if (v->maximized || v->fullscreen) {
		wlr_xwayland_surface_configure(v->xsurface, v->x, v->y,
			v->xsurface->width, v->xsurface->height);
		return;
	}
	view_configure(v, ev->x, ev->y, ev->width, ev->height);
	deco_update(v);
}

static void x11_request_activate(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, request_activate);
	if (v->mapped) {
		focus_view(v);
	}
}

static void x11_request_move(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, request_move);
	begin_interactive(v, CUR_MOVE, 0);
}

static void x11_request_resize(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, request_resize);
	struct wlr_xwayland_resize_event *ev = data;
	begin_interactive(v, CUR_RESIZE, ev->edges);
}

static void x11_request_maximize(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, request_maximize);
	if (v->mapped) {
		struct wlr_xwayland_surface *xs = v->xsurface;
		view_maximize(v, xs->maximized_horz || xs->maximized_vert);
		deco_update(v);
		schedule_state(v->server);
	}
}

static void x11_request_fullscreen(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, request_fullscreen);
	if (v->mapped) {
		view_fullscreen(v, v->xsurface->fullscreen);
	}
}

static void x11_request_minimize(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, request_minimize);
	struct wlr_xwayland_minimize_event *ev = data;
	if (v->mapped) {
		view_minimize(v, ev->minimize);
	}
}

static void x11_set_decorations(struct wl_listener *l, void *data) {
	struct view *v = wl_container_of(l, v, set_decorations);
	v->ssd = v->xsurface->decorations == WLR_XWAYLAND_SURFACE_DECORATIONS_ALL;
	deco_update(v);
}

/* override-redirect windows (menus, tooltips, dropdowns) */
static void unmanaged_map(struct wl_listener *l, void *data) {
	struct unmanaged *u = wl_container_of(l, u, map);
	struct server *s = u->server;
	u->tree = wlr_scene_subsurface_tree_create(s->layers[LYR_UNMANAGED], u->xsurface->surface);
	u->tree->node.data = u;
	wlr_scene_node_set_position(&u->tree->node, u->xsurface->x, u->xsurface->y);
	if (wlr_xwayland_surface_override_redirect_wants_focus(u->xsurface)) {
		keyboard_enter(s, u->xsurface->surface);
	}
}

static void unmanaged_unmap(struct wl_listener *l, void *data) {
	struct unmanaged *u = wl_container_of(l, u, unmap);
	if (u->tree) {
		wlr_scene_node_destroy(&u->tree->node);
		u->tree = NULL;
	}
	if (u->server->seat->keyboard_state.focused_surface == u->xsurface->surface) {
		focus_top_view(u->server);
	}
}

static void unmanaged_associate(struct wl_listener *l, void *data) {
	struct unmanaged *u = wl_container_of(l, u, associate);
	u->map.notify = unmanaged_map;
	wl_signal_add(&u->xsurface->surface->events.map, &u->map);
	u->unmap.notify = unmanaged_unmap;
	wl_signal_add(&u->xsurface->surface->events.unmap, &u->unmap);
}

static void unmanaged_dissociate(struct wl_listener *l, void *data) {
	struct unmanaged *u = wl_container_of(l, u, dissociate);
	wl_list_remove(&u->map.link);
	wl_list_remove(&u->unmap.link);
}

static void unmanaged_set_geometry(struct wl_listener *l, void *data) {
	struct unmanaged *u = wl_container_of(l, u, set_geometry);
	if (u->tree) {
		wlr_scene_node_set_position(&u->tree->node, u->xsurface->x, u->xsurface->y);
	}
}

static void unmanaged_request_configure(struct wl_listener *l, void *data) {
	struct unmanaged *u = wl_container_of(l, u, request_configure);
	struct wlr_xwayland_surface_configure_event *ev = data;
	wlr_xwayland_surface_configure(u->xsurface, ev->x, ev->y, ev->width, ev->height);
}

static void unmanaged_destroy(struct wl_listener *l, void *data) {
	struct unmanaged *u = wl_container_of(l, u, destroy);
	wl_list_remove(&u->associate.link);
	wl_list_remove(&u->dissociate.link);
	wl_list_remove(&u->destroy.link);
	wl_list_remove(&u->set_geometry.link);
	wl_list_remove(&u->request_configure.link);
	free(u);
}

static void server_new_xsurface(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, new_xsurface);
	struct wlr_xwayland_surface *xs = data;

	if (xs->override_redirect) {
		struct unmanaged *u = calloc(1, sizeof(*u));
		u->kind = NODE_UNMANAGED;
		u->server = s;
		u->xsurface = xs;
		u->associate.notify = unmanaged_associate;
		wl_signal_add(&xs->events.associate, &u->associate);
		u->dissociate.notify = unmanaged_dissociate;
		wl_signal_add(&xs->events.dissociate, &u->dissociate);
		u->destroy.notify = unmanaged_destroy;
		wl_signal_add(&xs->events.destroy, &u->destroy);
		u->set_geometry.notify = unmanaged_set_geometry;
		wl_signal_add(&xs->events.set_geometry, &u->set_geometry);
		u->request_configure.notify = unmanaged_request_configure;
		wl_signal_add(&xs->events.request_configure, &u->request_configure);
		return;
	}

	struct view *v = view_create(s, VIEW_X11);
	v->xsurface = xs;
	xs->data = v;
	v->associate.notify = x11_associate;
	wl_signal_add(&xs->events.associate, &v->associate);
	v->dissociate.notify = x11_dissociate;
	wl_signal_add(&xs->events.dissociate, &v->dissociate);
	v->destroy.notify = x11_destroy;
	wl_signal_add(&xs->events.destroy, &v->destroy);
	v->request_configure.notify = x11_request_configure;
	wl_signal_add(&xs->events.request_configure, &v->request_configure);
	v->request_activate.notify = x11_request_activate;
	wl_signal_add(&xs->events.request_activate, &v->request_activate);
	v->request_move.notify = x11_request_move;
	wl_signal_add(&xs->events.request_move, &v->request_move);
	v->request_resize.notify = x11_request_resize;
	wl_signal_add(&xs->events.request_resize, &v->request_resize);
	v->request_maximize.notify = x11_request_maximize;
	wl_signal_add(&xs->events.request_maximize, &v->request_maximize);
	v->request_fullscreen.notify = x11_request_fullscreen;
	wl_signal_add(&xs->events.request_fullscreen, &v->request_fullscreen);
	v->request_minimize.notify = x11_request_minimize;
	wl_signal_add(&xs->events.request_minimize, &v->request_minimize);
	v->set_title.notify = view_set_title;
	wl_signal_add(&xs->events.set_title, &v->set_title);
	v->set_app_id.notify = view_set_app_id;
	wl_signal_add(&xs->events.set_class, &v->set_app_id);
	v->set_decorations.notify = x11_set_decorations;
	wl_signal_add(&xs->events.set_decorations, &v->set_decorations);
}

static void xwayland_ready(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, xwayland_ready);
	wlr_xwayland_set_seat(s->xwayland, s->seat);
	struct wlr_xcursor *xc = wlr_xcursor_manager_get_xcursor(s->xcursor_mgr, "default", 1);
	if (xc) {
		struct wlr_xcursor_image *img = xc->images[0];
		wlr_xwayland_set_cursor(s->xwayland, wlr_xcursor_image_get_buffer(img),
			img->hotspot_x, img->hotspot_y);
	}
}

/* ------------------------------------------------------------------ */
/* session lock                                                       */

static void lock_surface_map(struct wl_listener *l, void *data) {
	struct lock_surface *ls = wl_container_of(l, ls, map);
	keyboard_enter(ls->server, ls->surface->surface);
}

static void lock_surface_destroy(struct wl_listener *l, void *data) {
	struct lock_surface *ls = wl_container_of(l, ls, destroy);
	wl_list_remove(&ls->map.link);
	wl_list_remove(&ls->destroy.link);
	free(ls);
}

static void lock_new_surface(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, lock_new_surface);
	struct wlr_session_lock_surface_v1 *surf = data;
	struct output *out;
	wl_list_for_each(out, &s->outputs, link) {
		if (out->wlr_output == surf->output) {
			struct wlr_scene_tree *t =
				wlr_scene_subsurface_tree_create(s->layers[LYR_LOCK], surf->surface);
			wlr_scene_node_set_position(&t->node, out->full.x, out->full.y);
			wlr_session_lock_surface_v1_configure(surf, out->full.width, out->full.height);
		}
	}
	struct lock_surface *ls = calloc(1, sizeof(*ls));
	ls->server = s;
	ls->surface = surf;
	ls->map.notify = lock_surface_map;
	wl_signal_add(&surf->surface->events.map, &ls->map);
	ls->destroy.notify = lock_surface_destroy;
	wl_signal_add(&surf->events.destroy, &ls->destroy);
}

static void lock_finish(struct server *s) {
	wl_list_remove(&s->lock_new_surface.link);
	wl_list_remove(&s->lock_unlock.link);
	wl_list_remove(&s->lock_destroy.link);
	s->lock = NULL;
}

static void lock_unlock(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, lock_unlock);
	lock_finish(s);
	s->locked = false;
	wlr_scene_node_set_enabled(&s->layers[LYR_LOCK]->node, false);
	focus_top_view(s);
	schedule_state(s);
}

static void lock_destroy(struct wl_listener *l, void *data) {
	/* locker died without unlocking: stay locked, a new locker may connect */
	struct server *s = wl_container_of(l, s, lock_destroy);
	lock_finish(s);
}

static void new_lock(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, new_lock);
	struct wlr_session_lock_v1 *lock = data;
	if (s->lock) {
		wlr_session_lock_v1_destroy(lock);
		return;
	}
	s->lock = lock;
	s->locked = true;
	reset_cursor_mode(s);
	s->focused_layer = NULL;
	wlr_seat_keyboard_notify_clear_focus(s->seat);
	/* drop stale lock surfaces of an earlier locker, keep the background */
	struct wlr_scene_node *n, *tmp;
	wl_list_for_each_safe(n, tmp, &s->layers[LYR_LOCK]->children, link) {
		if (n != &s->lock_bg->node) {
			wlr_scene_node_destroy(n);
		}
	}
	wlr_scene_node_set_enabled(&s->layers[LYR_LOCK]->node, true);
	s->lock_new_surface.notify = lock_new_surface;
	wl_signal_add(&lock->events.new_surface, &s->lock_new_surface);
	s->lock_unlock.notify = lock_unlock;
	wl_signal_add(&lock->events.unlock, &s->lock_unlock);
	s->lock_destroy.notify = lock_destroy;
	wl_signal_add(&lock->events.destroy, &s->lock_destroy);
	wlr_session_lock_v1_send_locked(lock);
	schedule_state(s);
}

/* ------------------------------------------------------------------ */
/* outputs                                                            */

static void update_output_boxes(struct server *s) {
	struct output *out;
	int maxw = 0, maxh = 0;
	wl_list_for_each(out, &s->outputs, link) {
		wlr_output_layout_get_box(s->output_layout, out->wlr_output, &out->full);
		if (out->full.x + out->full.width > maxw) maxw = out->full.x + out->full.width;
		if (out->full.y + out->full.height > maxh) maxh = out->full.y + out->full.height;
		arrange_layers(out);
	}
	wlr_scene_rect_set_size(s->lock_bg, maxw, maxh);
}

static void output_frame(struct wl_listener *l, void *data) {
	struct output *out = wl_container_of(l, out, frame);
	wlr_scene_output_commit(out->scene_output, NULL);
	struct timespec now;
	clock_gettime(CLOCK_MONOTONIC, &now);
	wlr_scene_output_send_frame_done(out->scene_output, &now);
}

static void output_request_state(struct wl_listener *l, void *data) {
	struct output *out = wl_container_of(l, out, request_state);
	const struct wlr_output_event_request_state *ev = data;
	wlr_output_commit_state(out->wlr_output, ev->state);
	update_output_boxes(out->server);
}

static void output_destroy(struct wl_listener *l, void *data) {
	struct output *out = wl_container_of(l, out, destroy);
	struct server *s = out->server;
	struct layer *ly, *tmp;
	wl_list_for_each_safe(ly, tmp, &s->layers_list, link) {
		if (ly->output == out) {
			ly->output = NULL;
			wlr_layer_surface_v1_destroy(ly->surface);
		}
	}
	wl_list_remove(&out->frame.link);
	wl_list_remove(&out->request_state.link);
	wl_list_remove(&out->destroy.link);
	wl_list_remove(&out->link);
	free(out);
	update_output_boxes(s);
}

static void server_new_output(struct wl_listener *l, void *data) {
	struct server *s = wl_container_of(l, s, new_output);
	struct wlr_output *wo = data;
	wlr_output_init_render(wo, s->allocator, s->renderer);

	struct wlr_output_state st;
	wlr_output_state_init(&st);
	wlr_output_state_set_enabled(&st, true);
	struct wlr_output_mode *mode = wlr_output_preferred_mode(wo);
	if (mode) {
		wlr_output_state_set_mode(&st, mode);
	}
	const char *scale = getenv("NOTHING_WM_SCALE");
	float sc = (scale && atof(scale) > 0) ? atof(scale) : 0;
	if (s->out_scale > 0) {
		sc = s->out_scale; /* set live via "config scale" since this session started */
	}
	if (sc > 0) {
		wlr_output_state_set_scale(&st, sc);
	}
	wlr_output_commit_state(wo, &st);
	wlr_output_state_finish(&st);

	struct output *out = calloc(1, sizeof(*out));
	out->server = s;
	out->wlr_output = wo;
	out->frame.notify = output_frame;
	wl_signal_add(&wo->events.frame, &out->frame);
	out->request_state.notify = output_request_state;
	wl_signal_add(&wo->events.request_state, &out->request_state);
	out->destroy.notify = output_destroy;
	wl_signal_add(&wo->events.destroy, &out->destroy);
	wl_list_insert(s->outputs.prev, &out->link);

	struct wlr_output_layout_output *lo = wlr_output_layout_add_auto(s->output_layout, wo);
	out->scene_output = wlr_scene_output_create(s->scene, wo);
	wlr_scene_output_layout_add_output(s->scene_layout, lo, out->scene_output);
	wlr_output_layout_get_box(s->output_layout, wo, &out->full);
	out->usable = out->full;
	update_output_boxes(s);

	if (s->locked && s->lock) {
		/* a locker must cover new outputs too; it gets notified through
		 * wl_output, until then the black background hides everything */
	}
}

/* ------------------------------------------------------------------ */

static void usage(const char *argv0) {
	printf("Usage: %s [-s startup-command] [-w workspaces]\n", argv0);
}

int main(int argc, char *argv[]) {
	wlr_log_init(getenv("NOTHING_WM_DEBUG") ? WLR_DEBUG : WLR_INFO, NULL);
	char *startup = NULL;
	int n_ws = 4;
	int c;
	while ((c = getopt(argc, argv, "s:w:h")) != -1) {
		switch (c) {
		case 's': startup = optarg; break;
		case 'w': n_ws = atoi(optarg); break;
		default: usage(argv[0]); return c == 'h' ? 0 : 1;
		}
	}
	signal(SIGPIPE, SIG_IGN);

	struct server s = {0};
	s.n_ws = n_ws < 1 ? 1 : (n_ws > MAX_WS ? MAX_WS : n_ws);
	s.next_id = 1;
	s.dark = true;
	parse_color("#D71921", s.accent);
	wl_list_init(&s.outputs);
	wl_list_init(&s.views);
	wl_list_init(&s.layers_list);
	wl_list_init(&s.keyboards);
	wl_list_init(&s.ipc_clients);
	const char *xl = getenv("XKB_DEFAULT_LAYOUT");
	if (xl) snprintf(s.kb_layout, sizeof(s.kb_layout), "%s", xl);
	const char *xv = getenv("XKB_DEFAULT_VARIANT");
	if (xv) snprintf(s.kb_variant, sizeof(s.kb_variant), "%s", xv);
	const char *xo = getenv("XKB_DEFAULT_OPTIONS");
	if (xo) snprintf(s.kb_options, sizeof(s.kb_options), "%s", xo);

	s.display = wl_display_create();
	s.loop = wl_display_get_event_loop(s.display);
	s.backend = wlr_backend_autocreate(s.loop, &s.session);
	if (!s.backend) {
		wlr_log(WLR_ERROR, "failed to create backend");
		return 1;
	}
	s.renderer = wlr_renderer_autocreate(s.backend);
	if (!s.renderer) {
		wlr_log(WLR_ERROR, "failed to create renderer");
		return 1;
	}
	wlr_renderer_init_wl_display(s.renderer, s.display);
	s.allocator = wlr_allocator_autocreate(s.backend, s.renderer);

	s.compositor = wlr_compositor_create(s.display, 6, s.renderer);
	wlr_subcompositor_create(s.display);
	wlr_data_device_manager_create(s.display);
	wlr_primary_selection_v1_device_manager_create(s.display);
	wlr_data_control_manager_v1_create(s.display);
	wlr_ext_data_control_manager_v1_create(s.display, 1);
	wlr_viewporter_create(s.display);
	wlr_presentation_create(s.display, s.backend, 2);
	wlr_single_pixel_buffer_manager_v1_create(s.display);
	wlr_fractional_scale_manager_v1_create(s.display, 1);
	wlr_screencopy_manager_v1_create(s.display);
	wlr_export_dmabuf_manager_v1_create(s.display);
	wlr_ext_image_copy_capture_manager_v1_create(s.display, 1);
	wlr_ext_output_image_capture_source_manager_v1_create(s.display, 1);
	wlr_idle_notifier_v1_create(s.display);
	wlr_idle_inhibit_v1_create(s.display);
	wlr_server_decoration_manager_set_default_mode(
		wlr_server_decoration_manager_create(s.display),
		WLR_SERVER_DECORATION_MANAGER_MODE_CLIENT);

	s.output_layout = wlr_output_layout_create(s.display);
	wlr_xdg_output_manager_v1_create(s.display, s.output_layout);
	s.new_output.notify = server_new_output;
	wl_signal_add(&s.backend->events.new_output, &s.new_output);

	s.scene = wlr_scene_create();
	s.scene_layout = wlr_scene_attach_output_layout(s.scene, s.output_layout);
	wlr_scene_set_gamma_control_manager_v1(s.scene,
		wlr_gamma_control_manager_v1_create(s.display));
	for (int i = 0; i < LYR_COUNT; i++) {
		s.layers[i] = wlr_scene_tree_create(&s.scene->tree);
	}
	for (int i = 0; i < MAX_WS; i++) {
		s.ws_tree[i] = wlr_scene_tree_create(s.layers[LYR_WINDOWS]);
		wlr_scene_node_set_enabled(&s.ws_tree[i]->node, i == 0);
	}
	float black[4] = {0, 0, 0, 1};
	s.lock_bg = wlr_scene_rect_create(s.layers[LYR_LOCK], 0, 0, black);
	wlr_scene_node_set_enabled(&s.layers[LYR_LOCK]->node, false);

	s.xdg_shell = wlr_xdg_shell_create(s.display, 6);
	s.xdg_shell->data = &s;
	s.new_xdg_toplevel.notify = server_new_xdg_toplevel;
	wl_signal_add(&s.xdg_shell->events.new_toplevel, &s.new_xdg_toplevel);
	s.new_xdg_popup.notify = server_new_xdg_popup;
	wl_signal_add(&s.xdg_shell->events.new_popup, &s.new_xdg_popup);

	s.layer_shell = wlr_layer_shell_v1_create(s.display, 4);
	s.new_layer.notify = server_new_layer;
	wl_signal_add(&s.layer_shell->events.new_surface, &s.new_layer);

	s.activation = wlr_xdg_activation_v1_create(s.display);
	s.request_activate.notify = request_activate;
	wl_signal_add(&s.activation->events.request_activate, &s.request_activate);

	s.lock_manager = wlr_session_lock_manager_v1_create(s.display);
	s.new_lock.notify = new_lock;
	wl_signal_add(&s.lock_manager->events.new_lock, &s.new_lock);

	s.tablet_mgr = wlr_tablet_v2_create(s.display);

	s.cursor = wlr_cursor_create();
	wlr_cursor_attach_output_layout(s.cursor, s.output_layout);
	const char *ctheme = getenv("XCURSOR_THEME");
	const char *csize = getenv("XCURSOR_SIZE");
	s.xcursor_mgr = wlr_xcursor_manager_create(ctheme, csize ? atoi(csize) : 24);
	s.relative_pointer = wlr_relative_pointer_manager_v1_create(s.display);
	s.cursor_shape = wlr_cursor_shape_manager_v1_create(s.display, 1);
	s.request_set_shape.notify = request_set_shape;
	wl_signal_add(&s.cursor_shape->events.request_set_shape, &s.request_set_shape);

	s.cursor_motion.notify = cursor_motion;
	wl_signal_add(&s.cursor->events.motion, &s.cursor_motion);
	s.cursor_motion_abs.notify = cursor_motion_abs;
	wl_signal_add(&s.cursor->events.motion_absolute, &s.cursor_motion_abs);
	s.cursor_button.notify = cursor_button;
	wl_signal_add(&s.cursor->events.button, &s.cursor_button);
	s.cursor_axis.notify = cursor_axis;
	wl_signal_add(&s.cursor->events.axis, &s.cursor_axis);
	s.cursor_frame.notify = cursor_frame;
	wl_signal_add(&s.cursor->events.frame, &s.cursor_frame);

	s.touch_down.notify = touch_down;
	wl_signal_add(&s.cursor->events.touch_down, &s.touch_down);
	s.touch_up.notify = touch_up;
	wl_signal_add(&s.cursor->events.touch_up, &s.touch_up);
	s.touch_motion.notify = touch_motion;
	wl_signal_add(&s.cursor->events.touch_motion, &s.touch_motion);
	s.touch_cancel.notify = touch_cancel;
	wl_signal_add(&s.cursor->events.touch_cancel, &s.touch_cancel);
	s.touch_frame.notify = touch_frame;
	wl_signal_add(&s.cursor->events.touch_frame, &s.touch_frame);

	s.tablet_tool_axis.notify = tablet_tool_axis;
	wl_signal_add(&s.cursor->events.tablet_tool_axis, &s.tablet_tool_axis);
	s.tablet_tool_proximity.notify = tablet_tool_proximity;
	wl_signal_add(&s.cursor->events.tablet_tool_proximity, &s.tablet_tool_proximity);
	s.tablet_tool_tip.notify = tablet_tool_tip;
	wl_signal_add(&s.cursor->events.tablet_tool_tip, &s.tablet_tool_tip);
	s.tablet_tool_button.notify = tablet_tool_button;
	wl_signal_add(&s.cursor->events.tablet_tool_button, &s.tablet_tool_button);

	s.new_input.notify = server_new_input;
	wl_signal_add(&s.backend->events.new_input, &s.new_input);
	s.seat = wlr_seat_create(s.display, "seat0");
	s.request_cursor.notify = seat_request_cursor;
	wl_signal_add(&s.seat->events.request_set_cursor, &s.request_cursor);
	s.request_set_selection.notify = seat_request_set_selection;
	wl_signal_add(&s.seat->events.request_set_selection, &s.request_set_selection);
	s.request_set_primary.notify = seat_request_set_primary;
	wl_signal_add(&s.seat->events.request_set_primary_selection, &s.request_set_primary);
	s.request_start_drag.notify = seat_request_start_drag;
	wl_signal_add(&s.seat->events.request_start_drag, &s.request_start_drag);
	s.start_drag.notify = seat_start_drag;
	wl_signal_add(&s.seat->events.start_drag, &s.start_drag);

	const char *socket = wl_display_add_socket_auto(s.display);
	if (!socket) {
		wlr_backend_destroy(s.backend);
		return 1;
	}

	s.xwayland = wlr_xwayland_create(s.display, s.compositor, true);
	if (s.xwayland) {
		s.xwayland_ready.notify = xwayland_ready;
		wl_signal_add(&s.xwayland->events.ready, &s.xwayland_ready);
		s.new_xsurface.notify = server_new_xsurface;
		wl_signal_add(&s.xwayland->events.new_surface, &s.new_xsurface);
		setenv("DISPLAY", s.xwayland->display_name, 1);
	} else {
		wlr_log(WLR_ERROR, "XWayland unavailable, X11 apps will not work");
	}

	if (!wlr_backend_start(s.backend)) {
		wlr_backend_destroy(s.backend);
		wl_display_destroy(s.display);
		return 1;
	}
	setenv("WAYLAND_DISPLAY", socket, 1);
	setenv("XDG_CURRENT_DESKTOP", "Nothing", 0);
	setenv("XDG_SESSION_TYPE", "wayland", 1);
	char pidbuf[16];
	snprintf(pidbuf, sizeof(pidbuf), "%d", (int)getpid());
	setenv("NOTHING_WM_PID", pidbuf, 1);
	ipc_init(&s, socket);
	wlr_cursor_set_xcursor(s.cursor, s.xcursor_mgr, "default");

	if (startup) {
		spawn(startup);
	}
	wlr_log(WLR_INFO, "nothing-wm running on WAYLAND_DISPLAY=%s DISPLAY=%s",
		socket, s.xwayland ? s.xwayland->display_name : "-");
	wl_display_run(s.display);

	struct ipc_client *ic, *itmp;
	wl_list_for_each_safe(ic, itmp, &s.ipc_clients, link) {
		ipc_client_destroy(ic);
	}
	unlink(s.ipc_path);
	wl_display_destroy_clients(s.display);
	if (s.xwayland) {
		wlr_xwayland_destroy(s.xwayland);
	}
	wlr_scene_node_destroy(&s.scene->tree.node);
	wlr_xcursor_manager_destroy(s.xcursor_mgr);
	wlr_cursor_destroy(s.cursor);
	wlr_allocator_destroy(s.allocator);
	wlr_renderer_destroy(s.renderer);
	wlr_backend_destroy(s.backend);
	wl_display_destroy(s.display);
	return 0;
}
