from PIL import Image, ImageDraw

def create_drone_icon():
    # 200x200 high res, will be resized by GUI
    size = (200, 200)
    # RGBA, (0,0,0,0) is fully transparent
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # White color
    color = (255, 255, 255, 255)
    
    # Center Body
    # draw.ellipse([80, 80, 120, 120], fill=color)
    
    # Arms (X shape)
    # Top Left to Bottom Right
    draw.line([40, 40, 160, 160], fill=color, width=18)
    # Top Right to Bottom Left
    draw.line([160, 40, 40, 160], fill=color, width=18)
    
    # Center Body (Draw over lines)
    draw.ellipse([70, 70, 130, 130], fill=color)

    # Rotors (Circles at ends)
    r_radius = 30
    # TL
    draw.ellipse([40-r_radius, 40-r_radius, 40+r_radius, 40+r_radius], outline=color, width=6)
    # TR
    draw.ellipse([160-r_radius, 40-r_radius, 160+r_radius, 40+r_radius], outline=color, width=6)
    # BL
    draw.ellipse([40-r_radius, 160-r_radius, 40+r_radius, 160+r_radius], outline=color, width=6)
    # BR
    draw.ellipse([160-r_radius, 160-r_radius, 160+r_radius, 160+r_radius], outline=color, width=6)
    
    img.save("drone_icon.png", "PNG")
    print("Icon created: drone_icon.png")

if __name__ == "__main__":
    create_drone_icon()
