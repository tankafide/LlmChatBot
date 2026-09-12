"""Submit and poll helpers for tests concerned with terminal application behavior."""

import time


def post_and_wait(client, url, **kwargs):
    response = client.post(url, **kwargs)
    if response.status_code != 202:
        return response
    body = kwargs["json"]
    assert response.json() == {
        "conversation_id": url.split("/")[-2],
        "request_id": body["request_id"],
        "status": "in_progress",
    }
    endpoint = url.removesuffix("/messages") + "/requests/" + body["request_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = client.get(endpoint)
        assert status.status_code == 200, status.text
        if status.json()["status"] != "in_progress":
            replay = client.post(url, **kwargs)
            assert replay.json() == status.json()["outcome"]
            return replay
        time.sleep(0.01)
    raise AssertionError("Admitted request did not reach a terminal state")


async def submit_and_wait(service, dealer, conversation, request_id, text):
    response = await service.submit(dealer, conversation, request_id, text)
    if response.status_code != 202:
        return response
    # Service tests can join owned work without timing polls.
    tasks = tuple(service._tasks.values())
    if tasks:
        import asyncio

        await asyncio.gather(*tasks)
    return await service.submit(dealer, conversation, request_id, text)
