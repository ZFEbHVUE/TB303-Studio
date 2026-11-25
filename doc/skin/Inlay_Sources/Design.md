# The Mk III instrument case

All dimensions are native pixels. The eleven factory bases are 1817 × 866. Each completed instrument is 1817 × 1110 and scales as a unit with the hit tests, lamps, readout and value windows.

* The illustrated foundation and the original control geometry come from the individual skin file. Each new switch uses cleaned samples from that instrument's own RUN, STOP, ACCENT and SLIDE fittings. Corners are scaled only with height; the centre can grow for longer legends.
* `chassis_materials.jpg` is the source sheet for the extra material between the original parts. The two Victorian cases also use dedicated restoration art in the unoccupied side areas. The original base PNGs are kept as supplied.
* `Python_Scripts/face_layout.py` owns the switch beds and pointer coordinates. `Python_Scripts/build_face_skins.py` seats the keys and builds the idle case and two moving switch states. `Python_Scripts/engraved_controls.py` displays values on the original case and draws the dial indices.
* `Python_Scripts/selector_art.py` uses the same bundled typeface for the field and its open list as the skin builder uses for the engraved keys; on hover, the highlight can move without changing the synth.
* The two DejaVu font files are provided with their license, so rebuilding the artwork does not depend on system fonts. No image-generation software or network connection is needed to rebuild or run a factory skin.

To rebuild one instrument, run `python Python_Scripts/build_face_skins.py steampunk` in the project folder. Omit the ID to rebuild all eleven. Factory artwork is prebuilt in `doc/skin/Inlaid_MkIII/<skin>/`. Custom backgrounds use their own material and fittings and do not borrow a stock strip.
