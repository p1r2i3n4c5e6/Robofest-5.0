import numpy as np

def nms(boxes, scores, iou_threshold):
    if len(boxes) == 0:
        return []

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]

    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)

        if order.size == 1:
            break

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter)

        inds = np.where(ovr <= iou_threshold)[0]
        order = order[inds + 1]

    return keep

def decode_outputs(output, conf_threshold, iou_threshold, img_w, img_h, input_size=640):
    # output shape is expected to be (84, 8400) for YOLOv8n
    # 84 = 4 (box) + 80 (classes)
    # 8400 = 80x80 + 40x40 + 20x20
    
    output = output.transpose() # (8400, 84)
    
    # Extract boxes and scores
    boxes = output[:, :4] # x_center, y_center, width, height
    # Only interest in person class (index 0)
    scores = output[:, 4] 
    
    mask = scores > conf_threshold
    boxes = boxes[mask]
    scores = scores[mask]
    
    if len(boxes) == 0:
        return [], []
        
    # Convert boxes from center-xywh to x1y1x2y2
    # And scale to original image size
    # Input size assumed to be square for simplicity here (640x640)
    
    new_boxes = []
    for box in boxes:
        xc, yc, w, h = box
        x1 = (xc - w/2) * (img_w / input_size)
        y1 = (yc - h/2) * (img_h / input_size)
        x2 = (xc + w/2) * (img_w / input_size)
        y2 = (yc + h/2) * (img_h / input_size)
        new_boxes.append([int(x1), int(y1), int(x2), int(y2)])
        
    new_boxes = np.array(new_boxes)
    keep = nms(new_boxes, scores, iou_threshold)
    
    return new_boxes[keep].tolist(), scores[keep].tolist()
