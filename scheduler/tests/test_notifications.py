import config
import notifications


def test_send_failure_notification_noop_without_webhook(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", None)
    # Must not raise even though no post is possible / expected.
    notifications.send_failure_notification("boom")


def test_send_failure_notification_posts_embed(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json

    monkeypatch.setattr("requests.post", fake_post)
    notifications.send_failure_notification("something broke")
    assert captured["url"] == "https://discord.example/webhook"
    assert captured["json"]["embeds"][0]["title"] == "Crawler failed"
    assert captured["json"]["embeds"][0]["description"] == "something broke"


def test_send_failure_notification_truncates_long_messages(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["json"] = json

    monkeypatch.setattr("requests.post", fake_post)
    notifications.send_failure_notification("x" * 1000)
    assert len(captured["json"]["embeds"][0]["description"]) == 500


def test_send_failure_notification_swallows_request_errors(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

    def failing_post(*args, **kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr("requests.post", failing_post)
    # Must not raise.
    notifications.send_failure_notification("boom")
