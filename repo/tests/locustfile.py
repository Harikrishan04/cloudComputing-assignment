from locust import HttpUser, between, task


class ParserUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task
    def parse(self):
        self.client.post(
            "/parse",
            json={"text": "Remind me tomorrow at 5 pm in Delhi"},
            name="/parse",
        )
