from memory.semantic_memory import SemanticMemory
from core.groq_backend import GroqBackend

class ClimateRiskModel:
    def __init__(self, semantic_memory, groq_backend):
        self.semantic_memory = semantic_memory
        self.groq_backend = groq_backend

    def predict_climate_risks(self, input_data):
        # използване на модели за прогноза на климатичните промени
        climate_risks = self.groq_backend.predict(input_data)
        return climate_risks

    def assess_climate_impacts(self, climate_risks):
        # оценка на въздействията от климатичните промени
        climate_impacts = self.semantic_memory.query(climate_risks)
        return climate_impacts

class System2Agent:
    def __init__(self, climate_risk_model):
        self.climate_risk_model = climate_risk_model

    def analyze_climate_risks(self, input_data):
        climate_risks = self.climate_risk_model.predict_climate_risks(input_data)
        climate_impacts = self.climate_risk_model.assess_climate_impacts(climate_risks)
        return climate_risks, climate_impacts
class SemanticMemory:
    def query(self, question, n=5, axis=None):
        return query(question, n=n, axis=axis)
    def remember(self, text, axis="GENERAL", source="agent"):
        return remember(text, axis=axis, source=source)
    def status(self):
        return status()
