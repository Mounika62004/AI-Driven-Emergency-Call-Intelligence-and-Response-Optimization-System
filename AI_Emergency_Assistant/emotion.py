import librosa
import numpy as np

# Emotion mapping to simplified categories
EMOTION_MAP = {
    "anger": "PANIC",
    "fear": "PANIC",
    "sadness": "DISTRESS",
    "disgust": "DISTRESS",
    "neutral": "CALM",
    "happiness": "CALM",
    "surprise": "PANIC"
}


def analyze_emotion(audio_path):
    """
    Analyze emotion from audio file using audio features
    Tuned specifically for emergency call scenarios

    Args:
        audio_path: Path to the audio file

    Returns:
        str: Mapped emotion category (PANIC, DISTRESS, or CALM)
    """
    try:
        print("Analyzing emotion from audio features...")

        # Load audio
        y, sr = librosa.load(audio_path, sr=16000, duration=10)

        # Extract audio features

        # 1. Energy/Intensity (loudness)
        rms = librosa.feature.rms(y=y)
        energy = np.mean(rms)
        energy_std = np.std(rms)  # Energy variation

        # 2. Zero crossing rate (voice quality/tension indicator)
        zcr = np.mean(librosa.feature.zero_crossing_rate(y))

        # 3. Spectral centroid (brightness/pitch of sound)
        spectral_centroid = np.mean(librosa.feature.spectral_centroid(y=y, sr=sr))
        spectral_std = np.std(librosa.feature.spectral_centroid(y=y, sr=sr))

        # 4. Tempo (speed of speech)
        try:
            tempo = librosa.feature.tempo(y=y, sr=sr)[0]
        except:
            tempo = 100  # default if tempo detection fails

        # 5. Pitch variation
        pitches, magnitudes = librosa.piptrack(y=y, sr=sr)
        pitch_values = []
        for t in range(pitches.shape[1]):
            index = magnitudes[:, t].argmax()
            pitch = pitches[index, t]
            if pitch > 0:
                pitch_values.append(pitch)

        pitch_variation = np.std(pitch_values) if len(pitch_values) > 0 else 0
        pitch_mean = np.mean(pitch_values) if len(pitch_values) > 0 else 0

        # 6. Spectral rolloff (frequency distribution)
        spectral_rolloff = np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr))

        print(f"Audio features - Energy: {energy:.4f} (std: {energy_std:.4f}), ZCR: {zcr:.4f}, "
              f"Spectral Centroid: {spectral_centroid:.2f}, Tempo: {tempo:.2f}, "
              f"Pitch Variation: {pitch_variation:.2f}")

        # Enhanced rule-based emotion detection for emergency calls
        # These thresholds are tuned for emergency situations

        raw_emotion = "neutral"  # default

        # Fear detection (high ZCR, moderate-high energy, high pitch variation)
        if zcr > 0.19 and energy > 0.065 and pitch_variation > 400:
            raw_emotion = "fear"

        # Angry detection (high energy, high spectral centroid, high variation)
        elif energy > 0.09 and spectral_centroid > 2200 and energy_std > 0.015:
            raw_emotion = "anger"

        # Sad/distressed detection (lower energy, moderate spectral features)
        elif energy < 0.08 and spectral_centroid < 1800 and pitch_variation < 600:
            raw_emotion = "sadness"

        # Surprised/shocked detection (high ZCR, variable energy)
        elif zcr > 0.18 and energy_std > 0.02:
            raw_emotion = "surprise"

        # Happy/relieved detection (moderate-high energy, higher pitch, stable)
        elif energy > 0.085 and spectral_centroid > 2100 and energy_std < 0.018:
            raw_emotion = "happiness"

        # Calm detection (low energy, low variation)
        elif energy < 0.075 and energy_std < 0.012 and zcr < 0.16:
            raw_emotion = "neutral"

        # Stressed/anxious (high ZCR with moderate energy - common in emergency calls)
        elif zcr > 0.20 and energy > 0.07:
            raw_emotion = "fear"

        # Default to neutral if none match strongly
        else:
            raw_emotion = "neutral"

        # Map the detected emotion to simplified category
        mapped_emotion = EMOTION_MAP.get(raw_emotion, "CALM")

        print(f"Detected raw emotion: {raw_emotion} -> Mapped to: {mapped_emotion}")
        return mapped_emotion

    except Exception as e:
        print(f"Error in emotion analysis: {str(e)}")
        # Return CALM as safe fallback
        return "CALM"