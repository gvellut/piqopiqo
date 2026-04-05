See /Users/guilhem/Documents/projects/github/apple_vision_ocr/src/apple_vision_ocr/__main__.py
This implements an OCR as with the Right click photo "Extract GPS Time Shift" but with Apple Vision (pyobjc related lib already installed here) instead of GCP Cloud Vision.
For a photo of a clock prints :
Found: 06:00:48 (Confidence: 1.00)  <=== this what is needed (photo of a clock : the first item of hte OCR will have the time, like with GCP Cloud Vision)
Found: Wed, March 4 (Confidence: 1.00)

In this project (piqopiqo) :

Add a Runtime Setting with an enum Value with GCP_VISION and APPLE_VISION. 
When the value is GCP_VISION : no change from now.
When the value is APPLE_VISION : use the apple vision process. Implement it. Add the _macos suffix to the function that calls the Apple Vision

Create a submodule of gpx2exif : ocr, where you will have a file for GCP Cloud Viion + one for Apple Vision.
Call from ocr_time_shift depending on the runtime setting
Otherwise same thing as now ( in term of time shift of dialogs)

Also : when the value is When the value is APPLE_VISION : do not display the Service Account JSON Key and GCP Project Override in the SEttings panel (External tools)