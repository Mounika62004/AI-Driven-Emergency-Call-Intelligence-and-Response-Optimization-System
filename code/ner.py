import spacy
import re

# Load SpaCy model
nlp = None


def load_nlp_model():
    global nlp
    if nlp is None:
        print("Loading SpaCy NLP model...")
        try:
            nlp = spacy.load("en_core_web_sm")
        except:
            print("Downloading SpaCy model...")
            import os
            os.system("python -m spacy download en_core_web_sm")
            nlp = spacy.load("en_core_web_sm")
        print("SpaCy model loaded successfully!")
    return nlp


def extract_entities(text):
    """
    Extract important entities from text (only priority level, emergency type, and location)

    Args:
        text: Transcribed text

    Returns:
        dict: Extracted entities
    """
    try:
        nlp_model = load_nlp_model()
        doc = nlp_model(text)

        entities = {
            'emergency_type': None,
            'priority_level': None,
            'location': None
        }

        # Extract location using SpaCy named entity recognition
        for ent in doc.ents:
            if ent.label_ == "GPE" or ent.label_ == "LOC":
                if not entities['location']:
                    entities['location'] = ent.text
                    break

        # Extract emergency type using keywords
        emergency_keywords = {
            'fire': ['fire', 'burning', 'smoke', 'flames'],
            'medical': ['heart attack', 'stroke', 'injury', 'injured', 'bleeding', 'unconscious', 'breathing',
                        'chest pain', 'ambulance'],
            'crime': ['robbery', 'theft', 'assault', 'shooting', 'gun', 'weapon', 'attack', 'violence', 'break in'],
            'accident': ['accident', 'crash', 'collision', 'hit', 'vehicle'],
            'disturbance': ['disturbance', 'noise', 'fight', 'argument', 'suspicious']
        }

        text_lower = text.lower()
        for emergency_type, keywords in emergency_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    entities['emergency_type'] = emergency_type
                    break
            if entities['emergency_type']:
                break

        # Extract addresses using simple pattern (as alternative to location)
        if not entities['location']:
            address_pattern = r'\d+\s+[\w\s]+(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|court|ct)'
            addresses = re.findall(address_pattern, text, re.IGNORECASE)
            if addresses:
                entities['location'] = addresses[0]

        # Determine priority level
        critical_keywords = ['fire', 'shooting', 'explosion', 'heart attack', 'stroke', 'dying', 'unconscious',
                             'severe bleeding']
        high_keywords = ['accident', 'injury', 'assault', 'robbery', 'chest pain']

        for keyword in critical_keywords:
            if keyword in text_lower:
                entities['priority_level'] = 'Critical'
                break

        if not entities['priority_level']:
            for keyword in high_keywords:
                if keyword in text_lower:
                    entities['priority_level'] = 'High'
                    break

        if not entities['priority_level']:
            entities['priority_level'] = 'Medium'

        print(f"Extracted entities: {entities}")
        return entities

    except Exception as e:
        print(f"Error in entity extraction: {str(e)}")
        return {
            'emergency_type': 'unknown',
            'priority_level': 'Medium',
            'location': None
        }