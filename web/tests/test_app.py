from app import create_app


def test_index():
    client = create_app().test_client()
    assert client.get("/").status_code == 200
