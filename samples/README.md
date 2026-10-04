# Validation media

`vehicle-validation.jpg` is the Ultralytics bus example image. `vehicle-validation.mp4` is a three-second clip made by translating that still image. The clip is useful for testing upload, segmentation, frame timing, tracking persistence and export without supplying a private video.

It is **not** a real convoy video or an accuracy benchmark. Movement in this clip is artificial image/camera motion. The vehicle model filters non-vehicle categories from this image.

Source: `https://raw.githubusercontent.com/ultralytics/assets/main/im/bus.jpg`. See `THIRD_PARTY_NOTICES.md`.


`vehicle-motion-demo.mp4` is an eight-second, 15 FPS synthetic clip with one bus cutout moving at 95 **source** pixels/second on static synthetic scenery. The bus image/mask comes from the same Ultralytics example and bundled model. `vehicle-motion-ground-truth.json` records each placement, source dimensions and timestamp. At the default 960-pixel analysis width, this corresponds to 71.25 analysis pixels/second. It exercises independent vehicle movement, tracking, masks and camera compensation. It is not field footage or a held-out accuracy benchmark.
