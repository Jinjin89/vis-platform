from typing import Any

from vis_platform_backend.contracts.common import ApiErrorEnvelope

type ResponseDocumentation = dict[int | str, dict[str, Any]]

NOT_FOUND_RESPONSE: ResponseDocumentation = {
    404: {
        "model": ApiErrorEnvelope,
        "description": "The requested resource was not found.",
    }
}

VALIDATION_RESPONSE: ResponseDocumentation = {
    422: {
        "model": ApiErrorEnvelope,
        "description": "The request does not match the API contract.",
    }
}

CONFLICT_RESPONSE: ResponseDocumentation = {
    409: {
        "model": ApiErrorEnvelope,
        "description": "The requested operation is not valid for the current run state.",
    }
}

UPSTREAM_RESPONSE: ResponseDocumentation = {
    502: {
        "model": ApiErrorEnvelope,
        "description": "The configured language-model provider failed.",
    },
    503: {
        "model": ApiErrorEnvelope,
        "description": "The language-model provider is not configured.",
    },
}

FORBIDDEN_RESPONSE: ResponseDocumentation = {
    403: {
        "model": ApiErrorEnvelope,
        "description": "Developer trace access was denied.",
    }
}
