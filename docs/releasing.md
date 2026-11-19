# Making a release

Releases are made by hand. A release is a git tag `vMAJOR.MINOR` and a GitHub
release carrying the built firmware image. The host tools and the OpenOCD
patch are used from the source tree at that tag.

1. Set the version in `firmware/proto.h` (`FW_VERSION_MAJOR`,
   `FW_VERSION_MINOR`). Raise `PROTO_VERSION` too if the USB protocol changed
   in a way older host tools cannot handle.
2. Move the entries under "Unreleased" in `CHANGELOG.md` to a new heading for
   the version.
3. Build and load the image, and check it on hardware:

   ```sh
   make -C firmware clean release
   .venv/bin/python host/pk2boot.py flash firmware/build/pk2probe.hex
   .venv/bin/python host/pk2probe.py info                  # reports the new version
   .venv/bin/python host/pk2probe.py --hvp program test/blink/blink.hex
   .venv/bin/python host/pk2debug.py --vdd 3300 load test/blink/blink.hex
   .venv/bin/python host/pk2debug.py step 3
   .venv/bin/python host/pk2debug.py unload
   ```

4. If anything under `openocd/openocd-src` changed, regenerate
   `openocd/pk2icsp-pic16f1.patch` as described in `openocd/README.md` and
   confirm it applies to a clean OpenOCD v0.12.0.
5. Commit, tag and publish:

   ```sh
   git commit -am "Release vX.Y"
   git tag -a vX.Y -m "vX.Y"
   git push origin main vX.Y
   gh release create vX.Y firmware/build/pk2probe-vX.Y.hex \
       --title "vX.Y" --notes "<the CHANGELOG section>"
   ```

The released image is the default build, which keeps the development
failsafe (see the README). Do not attach Microchip's stock firmware or
anything else from `backup/` to a release.
