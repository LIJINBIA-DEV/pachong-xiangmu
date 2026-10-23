import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from media_platform.weibo.login import WeiboLogin


class QRLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_switches_mobile_login_to_qr(self):
        page = MagicMock()
        page.goto = AsyncMock()
        switch = page.get_by_text.return_value.first
        switch.count = AsyncMock(return_value=1)
        switch.is_visible = AsyncMock(return_value=True)
        switch.click = AsyncMock()
        login = WeiboLogin('qrcode', MagicMock(), page)

        async def qr_image(*args, **kwargs):
            switch.click.assert_awaited_once()
            return 'data:image/png;base64,test'

        with patch('media_platform.weibo.login.utils.find_login_qrcode', side_effect=qr_image):
            self.assertEqual(await login._open_qrcode(), 'data:image/png;base64,test')

    async def test_missing_qr_is_error_not_successful_exit(self):
        login = WeiboLogin('qrcode', MagicMock(), MagicMock())
        with patch.object(login, '_open_qrcode', AsyncMock(return_value='')):
            with self.assertRaisesRegex(RuntimeError, '二维码'):
                await login.login_by_qrcode()


if __name__ == '__main__':
    unittest.main()
