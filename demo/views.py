import json

from django.core.files.base import ContentFile
from django.http.response import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import PIL.Image
import PIL.ImageDraw

from demo import models
from demo import level
from pmz.pmz import FaceDetection, ObjectDetection, SceneClassification

# load models
model_face = FaceDetection()
model_obj = ObjectDetection(cfg_path="pmz/pmz/object/yolov3/config/yolov3.cfg",
                            weights_path="pmz/pmz/object/yolov3/weights/yolov3.weights",
                            class_path="pmz/pmz/object/yolov3/data/coco.names")
model_scene = SceneClassification(model_path="pmz/pmz/scene/data/resnet50_places365.pth.tar",
                                  json_path="pmz/pmz/scene/data/model_class.json")
model_scene.loadFullModel()

privacy_level = level.privacyLevel()

@method_decorator(csrf_exempt, name='dispatch')
class ApiImage(View):
    def get(self, request, id):
        image = get_object_or_404(models.Image, id=id)
        return JsonResponse(image.json())

    def post(self, request, id=None):
        if id is None:
            image = models.Image.objects.create(file=request.FILES['image'], scanned=True)
            scenes = model_scene.inference(image_input=image.file.path)
            faces = model_face.inference(img_path=image.file.path)
            objects = model_obj.inference(img_path=image.file.path)
            
            # set initial privacy level
            top_scene = scenes[0]['name']
            obj_list = set()
            if len(faces):
                obj_list.add('face')
            for obj in objects:
                obj_list.add(obj['name'])
            obj2level = privacy_level.returnLevel(top_scene, obj_list)
            
            for i in scenes:
                image.scene_set.create(
                    name=i['name'],
                    score=i['score'],
                )
            for i in faces:
                x1, y1, x2, y2 = i['box_points']
                image.rect_set.create(
                    type='face',
                    left=x1,
                    top=y1,
                    right=x2,
                    bottom=y2,
                    level=obj2level['face'],
                    description='',
                )
            for i in objects:
                x1, y1, x2, y2 = i['box_points']
                image.rect_set.create(
                    type=i['name'],
                    left=x1,
                    top=y1,
                    right=x2,
                    bottom=y2,
                    level=obj2level[i['name']],
                    description='',
                )
            return JsonResponse(image.json())
        else:
            image = get_object_or_404(models.Image, id=id)
            data = json.load(request)
            for rect in image.rect_set.all():
                rect.level_corrected = data[str(rect.id)]
                rect.save()
            
            """更新模型，每张图片获得用户反馈后会被调用一次
                image.json = {
                    'scenes': [{'name': 'a', 'score': 0.6}, ...],
                    'rects': [{
                        'type': self.type,
                        'top': 0,
                        'left': 0,
                        'right': 100,
                        'bottom': 100,
                        'level': 1,  # 最初分析的等级
                        'level_corrected': 3,  # 用户标定的等级，只会是 0 或 3
                    }, ...],
                }
            """
            img_info = image.json()
            top_scene = img_info['scenes'][0]['name']
            userset_level = dict()
            for rect in img_info['rects']:
                userset_level[rect['type']] = rect['level_corrected']
            privacy_level.updateLevel(top_scene, userset_level)

            image.corrected.save(image.file.name, ContentFile(''))
            with PIL.Image.open(image.file.path) as im:
                draw = PIL.ImageDraw.Draw(im)
                for rect in image.rect_set.all():
                    if rect.level_corrected:
                        draw.rectangle(
                            (rect.left, rect.top, rect.right+1, rect.bottom+1),
                            fill=(128, 128, 128),
                        )
                im.save(image.corrected.path)
            return JsonResponse(image.json())
