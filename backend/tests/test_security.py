from security import hash_password, verify_password

# Hashes created with the OLD code (passlib) before the swap.
LEGACY_NORMAL = "$2b$12$VunXonVT7.8iWbhg7JpA.exJrO93ufRiuzytzGwGljk5cMMfwrIS2"
LEGACY_LONG = "$2b$12$lB/CSOvcuX3rQ8jXz/yjiutd2FEjig356JCk1Zmrp8uFSO/QXS4Lm"  # 80 x "A"


def test_legacy_hash_still_verifies():
    assert verify_password("legacy-test-password-123", LEGACY_NORMAL)


def test_legacy_hash_rejects_wrong_password():
    assert not verify_password("wrong-password", LEGACY_NORMAL)


def test_legacy_long_password_hash_still_verifies():
    assert verify_password("A" * 80, LEGACY_LONG)


def test_passwords_longer_than_72_bytes_are_cut_like_before():
    assert verify_password("A" * 72, LEGACY_LONG)
    assert not verify_password("A" * 71, LEGACY_LONG)


def test_new_hash_round_trip_and_format():
    hashed = hash_password("another-throwaway-1")
    assert hashed.startswith("$2b$12$")
    assert verify_password("another-throwaway-1", hashed)
    assert not verify_password("different", hashed)


def test_same_password_gets_different_hashes():
    assert hash_password("same-password-1") != hash_password("same-password-1")


def test_malformed_hash_returns_false_instead_of_crashing():
    assert not verify_password("anything", "not-a-real-hash")
