"""A drop-in stand-in for an OpenAI client that only imports the (slow, ~2 s) `openai` package and creates the
real client on first use, so the server starts faster. Behaves like `OpenAI(api_key=...)`."""


class LazyOpenAI:
    def __init__(self, api_key):
        self._api_key = api_key
        self._client = None

    def __getattr__(self, name):                      # only called for attributes not found on this object
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key)
        return getattr(self._client, name)
