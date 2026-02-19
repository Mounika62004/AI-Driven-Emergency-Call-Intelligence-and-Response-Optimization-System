import whisper
import torch

# Load Whisper model (using base model for lightweight performance)
model = None


def load_model():
    global model
    if model is None:
        # Use 'base' model for balance between speed and accuracy
        # Options: 'tiny', 'base', 'small', 'medium', 'large'
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading Whisper model on {device}...")
        model = whisper.load_model("base", device=device)
        print("Whisper model loaded successfully!")
    return model


def transcribe_audio(audio_path):
    """
    Transcribe audio file to text using OpenAI Whisper

    Args:
        audio_path: Path to the audio file

    Returns:
        str: Transcribed text
    """
    try:
        whisper_model = load_model()

        # Transcribe the audio
        result = whisper_model.transcribe(audio_path, language='en', fp16=False)

        transcript = result['text'].strip()
        print(f"Transcription: {transcript}")

        return transcript

    except Exception as e:
        print(f"Error in transcription: {str(e)}")
        raise Exception(f"Transcription failed: {str(e)}")