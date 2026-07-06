from app.core.security import decrypt_secret, encrypt_secret, generate_api_key, hash_secret, verify_secret


def test_encrypt_decrypt_secret_roundtrip():
    encrypted = encrypt_secret("refresh-token")

    assert encrypted
    assert encrypted != "refresh-token"
    assert decrypt_secret(encrypted) == "refresh-token"


def test_api_key_hashing():
    key = generate_api_key()
    hashed = hash_secret(key)

    assert key.startswith("mg_")
    assert verify_secret(key, hashed)
    assert not verify_secret(key + "x", hashed)

