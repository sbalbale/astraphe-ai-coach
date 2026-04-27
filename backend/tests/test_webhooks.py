import pandas as pd
from io import StringIO

def test_garmin_csv_parsing():
    # Sample Garmin data string
    csv_data = "Activity Type,Time,Normalized Power (NP)\nCycling,01:00:00,210"
    df = pd.read_csv(StringIO(csv_data))
    
    # Ensure columns map correctly to your internal models
    assert "Normalized Power (NP)" in df.columns
    assert df.iloc[0]["Activity Type"] == "Cycling"