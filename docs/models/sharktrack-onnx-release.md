SharkTrack, exported to ONNX for ReefScanner's default ONNX Runtime backend. ReefScanner downloads this file automatically on first use; you don't need to fetch it by hand.

**Model.** [SharkTrack](https://github.com/filippovarini/sharktrack) by Filippo Varini et al. ([paper](https://arxiv.org/abs/2407.20623)): YOLOv8, one `elasmobranch` class, trained on BRUVS footage. Licensed under the MIT License, as stated in the SharkTrack README. The weights are unchanged; only the file format differs.

**Export.** From `models/sharktrack.pt` with Ultralytics 8.4.143: `imgsz=640`, dynamic input, opset 17, simplified. Equivalent to:

```
reefscanner export-onnx
```

The input is dynamic, so frames are padded only to a multiple of 32, as Ultralytics runs the `.pt`. On ReefScanner's four test dives this file gives identical detections to the original `.pt` (72/72, same boxes and confidences).

**Note.** Ultralytics writes `AGPL-3.0` into the exported file's metadata, as it does for every export.

`sha256: ebbef2594720033066cc3eca0809c144b7092660a2018080a6042ae1ab565ff4`
