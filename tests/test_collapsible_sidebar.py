import unittest
import os

class TestCollapsibleSidebar(unittest.TestCase):
    def setUp(self):
        base_path = os.path.join(os.path.dirname(__file__), '..', 'templates', 'base.html')
        with open(base_path, 'r', encoding='utf-8') as f:
            self.content = f.read()

    def test_prerender_script_exists(self):
        """بررسی وجود اسکریپت پیش‌رندر در head برای جلوگیری از فلیکر"""
        self.assertIn("localStorage.getItem('sidebar_collapsed') === 'true'", self.content)
        self.assertIn("document.documentElement.classList.add('sidebar-mini')", self.content)

    def test_sidebar_toggle_bar_and_button_exist(self):
        """بررسی وجود نوار اختصاصی کنترل جمع‌شدن سایدبار و دکمه مربوطه"""
        self.assertIn('class="sidebar-desktop-toggle-bar', self.content)
        self.assertIn('id="sidebarCollapseBtn"', self.content)
        self.assertIn('onclick="toggleSidebarCollapse()"', self.content)

    def test_sidebar_floating_popup_container_exists(self):
        """بررسی وجود المان پاپ‌آپ شناور هوشمند برای هاور آیتم‌ها"""
        self.assertIn('id="sidebarFloatingPopup"', self.content)
        self.assertIn('class="sidebar-floating-popup"', self.content)

    def test_css_styles_for_mini_sidebar(self):
        """بررسی وجود استایل‌های فشرده‌سازی سایدبار و محتوا در عرض 992px به بالا"""
        self.assertIn('html.sidebar-mini .sidebar', self.content)
        self.assertIn('width: 68px !important;', self.content)
        self.assertIn('margin-right: 68px !important;', self.content)
        self.assertIn('.sidebar-floating-popup', self.content)
        self.assertIn('.sidebar-tooltip-content', self.content)
        self.assertIn('.sidebar-flyout-content', self.content)

    def test_javascript_functions_exist(self):
        """بررسی وجود توابع جاوااسکریپت کنترل جمع‌شدن و رهگیری هاور"""
        self.assertIn('function toggleSidebarCollapse()', self.content)
        self.assertIn('function hideSidebarFloatingPopup()', self.content)
        self.assertIn('function initSidebarHoverTooltips()', self.content)
        self.assertIn("localStorage.setItem('sidebar_collapsed'", self.content)

if __name__ == '__main__':
    unittest.main()
