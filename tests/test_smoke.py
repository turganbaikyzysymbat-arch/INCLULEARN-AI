from app import app, init_db
def test_health():
    app.config["TESTING"]=True
    with app.test_client() as c:
        assert c.get("/health").status_code==200
