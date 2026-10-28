project('nothing-wm', 'c',
  version: '0.1.0',
  license: 'MIT',
  default_options: ['c_std=c11', 'warning_level=2', 'werror=false'])

add_project_arguments('-DWLR_USE_UNSTABLE', '-Wno-unused-parameter', language: 'c')

wlroots = dependency('wlroots-0.20')
wayland_server = dependency('wayland-server')
wayland_protos = dependency('wayland-protocols')
xkbcommon = dependency('xkbcommon')
xcb = dependency('xcb')

wayland_scanner = find_program(
  dependency('wayland-scanner', native: true).get_variable('wayland_scanner'),
  native: true)

protocols = [
  wayland_protos.get_variable('pkgdatadir') / 'stable/xdg-shell/xdg-shell.xml',
  wayland_protos.get_variable('pkgdatadir') / 'staging/cursor-shape/cursor-shape-v1.xml',
  'protocols/wlr-layer-shell-unstable-v1.xml',
]
protocol_headers = []
foreach xml : protocols
  protocol_headers += custom_target(
    xml.underscorify() + '_h',
    input: xml,
    output: '@BASENAME@-protocol.h',
    command: [wayland_scanner, 'server-header', '@INPUT@', '@OUTPUT@'])
endforeach

executable('nothing-wm',
  ['nothing-wm.c', protocol_headers],
  dependencies: [wlroots, wayland_server, xkbcommon, xcb],
  install: true)
