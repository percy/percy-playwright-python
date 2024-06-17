# pylint: disable=protected-access
import json
from percy.cache import Cache


class PageMetaData:
    def __init__(self, page):
        self.page = page

    def __fetch_guid(self, obj):
        return obj._impl_obj._guid

    @property
    def framework(self):
        return "playwright"

    @property
    def page_guid(self):
        return self.__fetch_guid(self.page)

    @property
    def frame_guid(self):
        return self.__fetch_guid(self.page.main_frame)

    @property
    def browser_guid(self):
        return self.__fetch_guid(self.page.context.browser)

    @property
    def session_details(self):
        session_details = Cache.get_cache(self.browser_guid, Cache.session_details)
        if session_details is None:
            session_details = json.loads(
                self.page.evaluate(
                    "_ => {}", 'browserstack_executor: {"action": "getSessionDetails"}'
                )
            )
            Cache.set_cache(self.browser_guid, Cache.session_details, session_details)
            return session_details
        return session_details

    @property
    def automate_session_id(self):
        return self.session_details.get("hashed_id")
