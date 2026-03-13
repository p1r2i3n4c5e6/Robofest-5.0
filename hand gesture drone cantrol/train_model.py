import pandas as pd
import numpy as np
import tensorflow as tf
from sklearn.model_selection import train_test_split

DATASET_PATH = "gesture_dataset.csv"
MODEL_SAVE_PATH = "gesture_classifier.h5"
TFLITE_SAVE_PATH = "gesture_classifier.tflite"
NUM_CLASSES = 5

def main():
    print("Loading dataset...")
    try:
        df = pd.read_csv(DATASET_PATH)
    except FileNotFoundError:
        print(f"Error: {DATASET_PATH} not found. Please run collect_data.py first.")
        return

    # Extract features (X) and labels (y)
    X = df.drop('class', axis=1).values
    y = df['class'].values

    # One-hot encode labels
    y = tf.keras.utils.to_categorical(y, num_classes=NUM_CLASSES)

    # Split dataset
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    print(f"Dataset summary: {len(X_train)} training samples, {len(X_test)} testing samples.")

    # Build simple Neural Network (MLP)
    # 99 inputs -> 64 -> 32 -> 5 outputs
    model = tf.keras.models.Sequential([
        tf.keras.layers.Dense(64, activation='relu', input_shape=(X_train.shape[1],)),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.Dense(32, activation='relu'),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.Dense(NUM_CLASSES, activation='softmax')
    ])

    model.compile(optimizer='adam',
                  loss='categorical_crossentropy',
                  metrics=['accuracy'])

    print("Training model...")
    # Train
    history = model.fit(
        X_train, y_train, 
        epochs=50, 
        batch_size=16, 
        validation_data=(X_test, y_test)
    )

    # Evaluate
    loss, val_acc = model.evaluate(X_test, y_test, verbose=0)
    print(f"Final Validation Accuracy: {val_acc*100:.2f}%")

    if val_acc < 0.8:
        print("Warning: Accuracy is a bit low. Collect more data for better results!")

    # Save absolute H5 model
    model.save(MODEL_SAVE_PATH)
    print(f"Model saved as {MODEL_SAVE_PATH}")

    # Convert to TFLite for Raspberry Pi
    print("Converting to TensorFlow Lite...")
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    tflite_model = converter.convert()

    with open(TFLITE_SAVE_PATH, 'wb') as f:
        f.write(tflite_model)
    
    print(f"TFLite model saved as {TFLITE_SAVE_PATH}. Move this to your Raspberry Pi!")

if __name__ == "__main__":
    main()
