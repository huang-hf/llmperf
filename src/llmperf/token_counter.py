import tiktoken

def init_token_counter():
    print("Init token counter")
    tiktoken.get_encoding("cl100k_base")
    print("Token counter initialized")

def count_tokens(messages):
    tokens_per_message = 3
    tokens_per_name = 1
    num_tokens = 0
    encoding = tiktoken.get_encoding("cl100k_base")

    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            if not isinstance(value, str):
                continue
            num_tokens += len(encoding.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
    return num_tokens