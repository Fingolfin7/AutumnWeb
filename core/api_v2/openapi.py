from drf_spectacular.openapi import AutoSchema as SpectacularAutoSchema

# DELETE operations whose handlers read a JSON body. drf-spectacular only
# documents bodies for PUT/PATCH/POST, which hid these from the schema (and
# from the generated clients) even though the request= override declares them.
DELETE_BODY_OPERATIONS = {
    "notifications_schedules_destroy",  # {version}
    "push_subscriptions_destroy",  # {endpoint}
}


class AutoSchema(SpectacularAutoSchema):
    def _get_request_body(self, direction="request"):
        if self.method != "DELETE" or self.get_operation_id() not in DELETE_BODY_OPERATIONS:
            return super()._get_request_body(direction)
        self.method = "POST"
        try:
            return super()._get_request_body(direction)
        finally:
            self.method = "DELETE"
