"""Huawei Cloud FRS adapter; all face processing stays in the cloud service."""

import os
import tempfile
from pathlib import Path

from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkcore.http.formdata import FormFile
from huaweicloudsdkfrs.v2 import (
    AddFacesByFileRequest,
    AddFacesByFileRequestBody,
    CreateFaceSetReq,
    CreateFaceSetRequest,
    DetectFaceByFileRequest,
    DetectFaceByFileRequestBody,
    FrsClient,
    SearchFaceByFileRequest,
    SearchFaceByFileRequestBody,
)
from huaweicloudsdkfrs.v2.region.frs_region import FrsRegion


class HuaweiFaces:
    def __init__(self, face_set_name=None, temp_dir=None):
        self.face_set_name = face_set_name or os.getenv("FRS_FACE_SET", "class_checkin")
        self.temp_dir = Path(temp_dir or "data/private")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        ak = os.getenv("HUAWEICLOUD_SDK_AK")
        sk = os.getenv("HUAWEICLOUD_SDK_SK")
        if not ak or not sk:
            raise RuntimeError("请先设置 HUAWEICLOUD_SDK_AK 和 HUAWEICLOUD_SDK_SK")
        region = os.getenv("FRS_REGION", "cn-north-4")
        self.client = (
            FrsClient.new_builder(FrsClient)
            .with_credentials(BasicCredentials(ak, sk))
            .with_region(FrsRegion.value_of(region))
            .build()
        )

    def _with_file(self, photo: bytes, operation):
        # The SDK's FormFile requires a named, open file. Remove it after the call.
        with tempfile.TemporaryDirectory(dir=self.temp_dir) as directory:
            suffix = ".png" if photo.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg"
            path = Path(directory) / ("face" + suffix)
            path.write_bytes(photo)
            with path.open("rb") as file:
                return operation(file)

    def create_face_set(self):
        request = CreateFaceSetRequest()
        request.body = CreateFaceSetReq(face_set_name=self.face_set_name)
        return self.client.create_face_set(request)

    def enroll(self, photo: bytes, external_id: str) -> str:
        def operation(file):
            detect = DetectFaceByFileRequest()
            detect.body = DetectFaceByFileRequestBody(image_file=FormFile(file))
            found = self.client.detect_face_by_file(detect)
            if len(found.faces or []) != 1:
                raise ValueError("登记照必须恰好包含一张清晰人脸")
            file.seek(0)
            request = AddFacesByFileRequest()
            request.face_set_name = self.face_set_name
            request.body = AddFacesByFileRequestBody(
                image_file=FormFile(file), external_image_id=external_id, single=True
            )
            response = self.client.add_faces_by_file(request)
            faces = response.faces or []
            if len(faces) != 1 or not faces[0].face_id:
                raise RuntimeError("FRS 未返回有效的人脸 ID")
            return faces[0].face_id

        return self._with_file(photo, operation)

    def search(self, photo: bytes):
        def operation(file):
            request = SearchFaceByFileRequest()
            request.face_set_name = self.face_set_name
            request.body = SearchFaceByFileRequestBody(image_file=FormFile(file), top_n=2)
            response = self.client.search_face_by_file(request)
            faces = response.faces or []
            if not faces:
                return None, None
            best = faces[0]
            threshold = float(os.getenv("FRS_MATCH_THRESHOLD", "0.93"))
            gap = float(os.getenv("FRS_MATCH_MIN_GAP", "0.03"))
            if best.similarity is None or best.similarity < threshold:
                return None, best.similarity
            if len(faces) > 1 and faces[1].similarity is not None and best.similarity - faces[1].similarity < gap:
                return None, best.similarity
            return best.face_id, best.similarity

        return self._with_file(photo, operation)
