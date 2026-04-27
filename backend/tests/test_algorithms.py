from app.services.algorithms import calculate_cycling_tss, normalize_rowing_watts

def test_watt_normalization():
    # Rowing watts must be 12% more costly than cycling
    rowing_power = 200
    expected_cycling_equiv = 224.0 # 200 * 1.12
    assert normalize_rowing_watts(rowing_power) == expected_cycling_equiv

def test_cycling_tss_accuracy():
    # 1 hour at 200W with 250W FTP should be exactly 64.0 TSS
    duration = 3600
    np = 200
    ftp = 250
    assert calculate_cycling_tss(duration, np, ftp) == 64.0

def test_alpine_override_logic():
    # Skiing > 4 hours triggers a 50% gym volume cut
    ski_duration_minutes = 250 # 4.1 hours
    # This would be integrated into your 'Coach's Orders' generation logic
    pass