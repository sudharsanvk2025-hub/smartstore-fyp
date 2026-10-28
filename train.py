from ultralytics import YOLO

if __name__ == "__main__":      # needed on Windows when training uses the GPU
    model = YOLO("yolov8s.pt")  # "small" model: more accurate than nano, still fast on the RTX 4050

    model.train(
        data="smartstore-products.v2i.yolov8/data.yaml",
        epochs=100,        # maximum rounds of training
        patience=20,       # stop early if it stops improving for 20 rounds
        imgsz=640,
        batch=16,
        device=0,          # train on the NVIDIA GPU
        workers=2,
        name="smartstore_v2",
    )

    print("Training complete!")
    print("Model saved to: runs/detect/smartstore_v2/weights/best.pt")