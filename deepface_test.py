from deepface import DeepFace
import cv2

print("Taking your photo for test...")
cap = cv2.VideoCapture(0)
ret, frame = cap.read()
cv2.imwrite("test_photo.jpg", frame)
cap.release()

print("Photo saved. Running face analysis...")
result = DeepFace.analyze("test_photo.jpg", actions=["age", "gender", "emotion"])
print(f"Age estimate: {result[0]['age']}")
print(f"Gender: {result[0]['dominant_gender']}")
print(f"Emotion: {result[0]['dominant_emotion']}")
print("\nDeepFace is working correctly!")