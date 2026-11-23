"""Reject retired inference before request limits, sessions and body access."""

from django.http import JsonResponse

RETIRED_PATHS = frozenset(
    {"/v1/dictations", "/v1/text", "/v1/text-actions/execute", "/v1/usage"}
)


class InferenceRetirementMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in RETIRED_PATHS:
            response = JsonResponse(
                {"code": "inference_retired", "update_required": True}, status=410
            )
            response["Cache-Control"] = "no-store"
            return response
        return self.get_response(request)
