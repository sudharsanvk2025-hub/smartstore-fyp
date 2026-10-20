from ultralytics import YOLO

# Load base YOLOv8 nano model
model = YOLO("yolov8n.pt")

# Train on your dataset
results = model.train(
    data="smartstore-products.v1i.yolov8/data.yaml",  # update this path if different
    epochs=50,
    imgsz=640,
    batch=8,
    name="smartstore_v1",
    device="cpu"
)

print("Training complete!")
print(f"Model saved to: runs/detect/smartstore_v1/weights/best.pt")