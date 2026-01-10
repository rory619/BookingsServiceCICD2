from unittest.mock import AsyncMock, MagicMock, patch

#create booking and force users service validation to work
def create_booking_ok(client, payload=None):
    payload = payload or {"user_id": 1, "course_id": 10, "status": "confirmed"}
    with patch(
        "app.main.check_user_with_circuit_breaker",
        return_value=(True, "checked"),
    ):
        r = client.post("/api/bookings", json=payload)

    assert r.status_code == 201
    return r.json()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_booking(client):
    data = create_booking_ok(client)
    assert "id" in data
#Returns an ID when works

def test_create_booking_user_not_found(client):
    with patch(
        "app.main.check_user_with_circuit_breaker",
        return_value=(False, "checked"),
    ):
        r = client.post(
            "/api/bookings",
            json={"user_id": 999, "course_id": 10, "status": "confirmed"},
        )

    assert r.status_code == 404


def test_create_booking_users_down_sets_pending(client):
    with patch(
        "app.main.check_user_with_circuit_breaker",
        return_value=(None, "skipped_users_down"),
    ):
        r = client.post(
            "/api/bookings",
            json={"user_id": 1, "course_id": 10, "status": "confirmed"},
        )

    assert r.status_code == 201
    assert r.json()["status"] == "pending_user_check"
#If users isnt available create it but mark as pending

def test_list_bookings(client):
    create_booking_ok(client)
    r = client.get("/api/bookings?limit=10&offset=0")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 1


def test_get_booking(client):
    created = create_booking_ok(client)
    booking_id = created["id"]

    r = client.get(f"/api/bookings/{booking_id}")
    assert r.status_code == 200
    assert r.json()["id"] == booking_id


def test_get_booking_404(client):
    r = client.get("/api/bookings/999999")
    assert r.status_code == 404


def test_update_booking(client):
    created = create_booking_ok(client)
    booking_id = created["id"]

    with patch(
        "app.main.check_user_with_circuit_breaker",
        return_value=(True, "checked"),
    ):
        r = client.put(
            f"/api/bookings/{booking_id}",
            json={"user_id": 1, "course_id": 10, "status": "cancelled"},
        )

    assert r.status_code == 200
    assert r.json()["id"] == booking_id
#User validation is mocked so not relying on userService

def test_update_booking_404(client):
    with patch(
        "app.main.check_user_with_circuit_breaker",
        return_value=(True, "checked"),
    ):
        r = client.put(
            "/api/bookings/999999",
            json={"user_id": 1, "course_id": 10, "status": "cancelled"},
        )
#Creating missing booking return error 404
    assert r.status_code == 404


def test_delete_booking(client):
    created = create_booking_ok(client)
    booking_id = created["id"]

    r = client.delete(f"/api/bookings/{booking_id}")
    assert r.status_code == 204


def test_delete_booking_404(client):
    r = client.delete("/api/bookings/999999")
    assert r.status_code == 404


def test_proxy_greet(client):
    class FakeResp:
        def json(self):
            return {"hello": "world"}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return FakeResp()

    with patch("app.main.httpx.Client", FakeClient):
        r = client.get("/api/proxy-greet?name=paul")

    assert r.status_code == 200
    assert r.json()["service_b"] is True
#create a fake context manager so it doesnt call network when testing endpoints

def test_publish_order(client):
    fake_conn = MagicMock()
    fake_conn.channel = AsyncMock()
    fake_conn.close = AsyncMock()

    fake_channel = MagicMock()
    fake_channel.default_exchange = MagicMock()
    fake_channel.default_exchange.publish = AsyncMock()
    fake_conn.channel.return_value = fake_channel

    with (
        patch(
            "app.main.aio_pika.connect_robust",
            new=AsyncMock(return_value=fake_conn),
        ),
        patch(
            "app.main.aio_pika.Message",
            return_value=MagicMock(),
        ),
    ):
        r = client.post("/order", json={"order_id": 1})

    assert r.status_code == 200
    assert r.json()["status"] == "Message sent"
#Verify RabbitMQ publish here without broker connection to test publishing flow

def test_order_created_event(client): #testing porder create event without using RabbitMQ, verifies if corrrect event name has been used
    fake_conn = MagicMock()
    fake_conn.channel = AsyncMock()
    fake_conn.close = AsyncMock()

    fake_channel = MagicMock()
    fake_exchange = MagicMock()
    fake_exchange.publish = AsyncMock()

    fake_channel.declare_exchange = AsyncMock(return_value=fake_exchange)
    fake_conn.channel.return_value = fake_channel

    with (
        patch(
            "app.main.aio_pika.connect_robust",
            new=AsyncMock(return_value=fake_conn),
        ),
        patch(
            "app.main.aio_pika.Message",
            return_value=MagicMock(),
        ),
    ):
        r = client.post("/order/create", json={"order_id": 123})

    assert r.status_code == 200
    assert r.json()["event"] == "order.created"


def test_payment_success_event(client): #Testing payment/success withoutRabbitMQ needing to be running, confirms payment.success is returns 
    fake_conn = MagicMock()
    fake_conn.channel = AsyncMock()
    fake_conn.close = AsyncMock()

    fake_channel = MagicMock()
    fake_exchange = MagicMock()
    fake_exchange.publish = AsyncMock()

    fake_channel.declare_exchange = AsyncMock(return_value=fake_exchange)
    fake_conn.channel.return_value = fake_channel

    with (
        patch(
            "app.main.aio_pika.connect_robust",
            new=AsyncMock(return_value=fake_conn),
        ),
        patch(
            "app.main.aio_pika.Message",
            return_value=MagicMock(),
        ),
    ):
        r = client.post("/payment/success", json={"payment_id": 999})

    assert r.status_code == 200
    assert r.json()["event"] == "payment.success"
