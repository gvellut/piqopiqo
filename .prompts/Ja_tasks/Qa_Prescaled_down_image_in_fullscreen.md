I need to test various method for the down scaling during fullscreen overlay (initial view) when the image is bigger than the rendering buffer (not for the 100% view or up : the 100% can also be if the image is smaller than the buffer ; for images like that, the sscheme will have no effect).

Add a runtime setting src/piqopiqo/ssf/settings_state.py
PRE_SCALE_DOWN

Value is enum ScaleDownMethod (to be defined) : NONE (default value set for now), QT_SMOOTH, PILLOW_LANCZOS

NONE is exaclty like now : the scale down is done by the painter that renders to the rendering buffer using a scale down and QPainter.SmoothPixmapTransform as render hint.

Add a second runtime setting :
PRE_100P
boolean true and false : will only be take into account sens for the QT_SMOOTH, PILLOW_LANCZOS. Otherwise will have no effect for None

For the others : 

For the images large enough that they need to be scaled down when displayed as the base view in fullscreen :
You will need to pre scale the image and cache it (for now for just the current lifetime of the 100% QPIxmap of the current image : i think (confim) it is loaded when the image is set as the current one in Fullscreen and discarded when going to another photo using the arrows or when exiting fullscreen : for the scaled down, it should follow the same lifecycle). The cache is when going from the base view (scaled down) to 100% and back : the scaled down is kept around.

The 100% pixmap will not use the scaled down image scaled up : it will use its own qpixmap loaded from the base file (and not scaled). The further zoom will use that 100% version. This is the current behaviour. The PRE_SCALE_DOWN behaviour only concerns the base view.

For the 2 methods below : only load when needed and cache ; discard when not needed. By that I mean : If the base view is displayed first, create the pre scaled down version but not the 100% QPixmap. Only create 100% version when the zoom goes to that. If the 100% or more zoom is displayed first (for example : if the user navigated from an image that was already zoomed in : the zoom is preserved)  : load the 100% version but not the scaled down. Only if the user goes down to the base view will you load it.
Unless PRE_100P is True : then load the 2 (scaled down and 100%) at the same time. When one is loaded, the other is too. It is for testing the behaviour and latency.

Depending on the value of the setting.
The scaled down use the width / height of the rendering buffer (like what is done now for the base view ; the QPainter does it).

QT_SMOOTH : 

something like that :
Use Qt scaled


image = QImage("high_res_photo.jpg")

# 2. Scale using the SmoothTransformation (Area-averaging)
# This is much better than the painter.scale() method
scaled_image = image.scaled(
    target_width, 
    target_height, 
    Qt.AspectRatioMode.KeepAspectRatio, 
    Qt.TransformationMode.SmoothTransformation  # <--- This is the key
)

# 3. Convert to Pixmap for fast drawing
return QPixmap.fromImage(scaled_image)


PILLOW_LANCZOS :
something like that
Use pillow resize iwth Reampling LANCZOS

def get_high_quality_pixmap(image_path, width, height):
    # 1. Open with Pillow
    pil_img = Image.open(image_path)
    
    # 2. Use Lanczos resampling (best for downscaling)
    # This is much higher quality than Qt's SmoothTransformation
    pil_img = pil_img.resize((width, height), resample=Image.Resampling.LANCZOS)
    
    # 3. Convert Pillow Image to QImage
    # (Handling RGB vs RGBA depending on your source)
    if pil_img.mode == "RGB":
        format = QImage.Format_RGB888
    else:
        format = QImage.Format_RGBA8888
        
    data = pil_img.tobytes("raw", pil_img.mode)
    qimg = QImage(data, pil_img.size[0], pil_img.size[1], format)
    
    return QPixmap.fromImage(qimg)