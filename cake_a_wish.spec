# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Cake A Wish
# Build: pyinstaller cake_a_wish.spec

block_cipher = None

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates',                        'templates'),
        ('static',                           'static'),
        ('blow_detection/face_landmarker.task', 'blow_detection'),
        ('label_printer/frames',             'label_printer/frames'),
    ],
    hiddenimports=[
        # uvicorn dynamic imports
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        # anyio / starlette
        'anyio',
        'anyio._backends._asyncio',
        'starlette.routing',
        'starlette.middleware',
        'starlette.middleware.base',
        # file uploads
        'multipart',
        'python_multipart',
        # brother_ql backends (loaded by string at runtime)
        'brother_ql.backends',
        'brother_ql.backends.helpers',
        'brother_ql.backends.network',
        'brother_ql.backends.pyusb',
        'brother_ql.backends.linux_kernel',
        # pyusb
        'usb',
        'usb.core',
        'usb.backend',
        'usb.backend.libusb1',
        'usb.backend.libusb0',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CakeAWish',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,   # keep console so errors are visible; set False once stable
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CakeAWish',
)

# macOS .app bundle
app = BUNDLE(
    coll,
    name='CakeAWish.app',
    icon=None,
    bundle_identifier='com.cake-a-wish.app',
    info_plist={
        'NSCameraUsageDescription': 'Cake A Wish uses the camera to capture photos.',
        'NSMicrophoneUsageDescription': 'Cake A Wish uses the microphone for blow detection.',
        'LSUIElement': False,
    },
)
