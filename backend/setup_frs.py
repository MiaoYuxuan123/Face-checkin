"""Create the cloud face set once before accepting registrations."""

from backend.faces import HuaweiFaces


if __name__ == "__main__":
    service = HuaweiFaces()
    service.create_face_set()
    print(f"FRS 人脸库已创建：{service.face_set_name}")
