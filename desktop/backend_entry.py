"""Entry point for the standalone desktop backend.

PyInstaller freezes this file into ``habit-quest-backend.exe``. The build also
bundles the ``static`` folder, so the resulting executable carries the whole
game and the Electron shell can start it on a machine with no Python at all.

It is only used by the packaging build -- ``python -m habitquest.desktop`` is
the same program, launched from source.
"""

from habitquest.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
