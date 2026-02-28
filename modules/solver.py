import json
import random


def solve_3d_captcha(session, challenge, decrypted_object):
    import io
    from PIL import Image
    from ultralytics import YOLO

    with open('class_mapping.json', 'r') as f:
        class_mapping = json.load(f)
    id_to_class = {v: k for k, v in class_mapping.items()}

    model = YOLO('best.pt')

    shapes_response = session.get(challenge['question']['url1'])

    img = Image.open(io.BytesIO(shapes_response.content))
    results = model(img, conf=0.5, verbose=False)

    detected_results = []
    for result in results:
        boxes = result.boxes
        if boxes is not None:
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                cls = int(box.cls[0].cpu().numpy())
                label = id_to_class.get(cls, f"class_{cls}")
                center_x = int((x1 + x2) // 2)
                center_y = int((y1 + y2) // 2)
                detected_results.append({"label": label, "coords": [center_x, center_y]})

    label_groups = {}
    for detection in detected_results:
        label = detection["label"]
        if label not in label_groups:
            label_groups[label] = []
        label_groups[label].append(detection["coords"])

    x1, y1, x2, y2 = None, None, None, None
    for label, coords_list in label_groups.items():
        if len(coords_list) > 1:
            x1, y1 = coords_list[0][0], coords_list[0][1]
            x2, y2 = coords_list[1][0], coords_list[1][1]
            break

    width, height = img.size

    time1 = random.randint(10000, 20000)
    time2 = time1 + random.randint(200, 1000)

    captcha_solution = {
        'modified_img_width': width,
        'id': challenge['id'],
        'mode': '3d',
        'reply': [{'x': x1, 'y': y1, 'time': time1}, {'x': x2, 'y': y2, 'time': time2}],
        'models': {},
        'log_params': {},
        'reply2': [],
        'models2': {},
        'version': 2,
        'verify_id': decrypted_object['data']['verify_id'],
        'verify_requests': [{
            'id': challenge['id'],
            'modified_img_width': width,
            'mode': '3d',
            'reply': [{'x': x1, 'y': y1, 'time': time1}, {'x': x2, 'y': y2, 'time': time2}],
            'models': {},
            'reply2': [],
            'models2': {},
            'events': '{"userMode":0}'
        }],
        'events': '{"userMode":0}'
    }

    return captcha_solution
