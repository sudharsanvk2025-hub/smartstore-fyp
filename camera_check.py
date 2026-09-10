import cv2

for i in range(3):
    print(f"Opening Camera {i} — look at which camera turns on. Press Q to go to next.")
    cap = cv2.VideoCapture(i)
    while True:
        ret, frame = cap.read()
        cv2.imshow(f"Camera {i} — press Q for next", frame)
        if cv2.waitKey(1) == ord('q'):
            break
    cap.release()
    cv2.destroyAllWindows()

print("Done — note which camera number was which.")