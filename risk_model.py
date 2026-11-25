
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import pickle
import itertools

# Sample training dataset
data = []

for location_risk, night, crowd_level, incident_history in itertools.product(
    range(11), range(2), range(3), range(6)
):
    score = (
        location_risk * 0.35
        + night * 2
        + (2 - crowd_level) * 1.5
        + incident_history * 1.2
    )

    if score < 5:
        risk = "LOW"
    elif score < 9:
        risk = "MEDIUM"
    else:
        risk = "HIGH"

    data.append([
        location_risk,
        night,
        crowd_level,
        incident_history,
        risk
    ])

df = pd.DataFrame(data, columns=[
    "location_risk",
    "night",
    "crowd_level",
    "incident_history",
    "risk"
])

# Input and output
X = df[[
    "location_risk",
    "night",
    "crowd_level",
    "incident_history"
]]

y = df["risk"]

# Split dataset
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

# Train ML model
model = RandomForestClassifier(
    n_estimators=100,
    random_state=42
)

model.fit(X_train, y_train)

# Test model
predictions = model.predict(X_test)

accuracy = accuracy_score(y_test, predictions)

print("Model Training Completed!")
print("Model Accuracy:", round(accuracy * 100, 2), "%")

# Save trained model
with open("tourist_risk_model.pkl", "wb") as file:
    pickle.dump(model, file)

print("Model saved successfully!")
