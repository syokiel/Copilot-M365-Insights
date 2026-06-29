"""
M365 Admin Center — Office 365 / Microsoft 365 Apps usage CSV importer.

Supported files (paths set via M365USAGE_* and BILLING_LICENCES env vars):
  Office365ActivationsUserDetail_*.csv          → fetch_activations_users
  Office365ServicesUserCounts_*.csv             → fetch_services_counts
  Office365ActiveUserActivityCounts_*.csv       → fetch_activity_counts
  Office365ActiveUserCounts_*.csv               → fetch_active_user_counts
  Office365ActiveUserDetail_*.csv               → fetch_active_users_detail
  ProPlusUsagePlatformsUserCountsV2_*.csv       → fetch_proplus_platforms
  ProPlusUsageUserCountsV2_*.csv                → fetch_proplus_counts
  ProPlusUsageUserDetailV2_*.csv                → fetch_proplus_detail
  ProductList_*.csv                             → fetch_billing_licences
"""
import csv
from pathlib import Path


def _read(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, newline='', encoding='utf-8-sig') as fh:
        return list(csv.DictReader(fh))


def _int(v) -> int | None:
    try:
        s = str(v).strip().replace(',', '')
        return int(s) if s else None
    except (ValueError, TypeError):
        return None


def _bool(v) -> int:
    return 1 if str(v).strip().upper() in ('YES', 'TRUE', '1') else 0


class M365UsageReportImporter:
    def __init__(
        self,
        activations_users_path: str = "",
        services_counts_path: str = "",
        activity_counts_path: str = "",
        active_user_counts_path: str = "",
        active_users_detail_path: str = "",
        proplus_platforms_path: str = "",
        proplus_counts_path: str = "",
        proplus_detail_path: str = "",
        billing_licences_path: str = "",
    ) -> None:
        self._activations_users_path   = activations_users_path
        self._services_counts_path     = services_counts_path
        self._activity_counts_path     = activity_counts_path
        self._active_user_counts_path  = active_user_counts_path
        self._active_users_detail_path = active_users_detail_path
        self._proplus_platforms_path   = proplus_platforms_path
        self._proplus_counts_path      = proplus_counts_path
        self._proplus_detail_path      = proplus_detail_path
        self._billing_licences_path    = billing_licences_path

    def fetch_activations_users(self) -> list[dict]:
        out = []
        for r in _read(self._activations_users_path):
            out.append({
                'user_principal_name': r.get('User Principal Name', ''),
                'product_type':        r.get('Product Type', ''),
                'report_refresh_date': r.get('Report Refresh Date', ''),
                'display_name':        r.get('Display Name', ''),
                'last_activated_date': r.get('Last Activated Date', ''),
                'windows':             _bool(r.get('Windows', '')),
                'mac':                 _bool(r.get('Mac', '')),
                'windows_10_mobile':   _bool(r.get('Windows 10 Mobile', '')),
                'ios':                 _bool(r.get('iOS', '')),
                'android':             _bool(r.get('Android', '')),
                'shared_computer':     _bool(r.get('Activated On Shared Computer', '')),
            })
        return out

    def fetch_services_counts(self) -> list[dict]:
        out = []
        for r in _read(self._services_counts_path):
            out.append({
                'report_refresh_date': r.get('Report Refresh Date', ''),
                'report_period':       r.get('Report Period', ''),
                'exchange_active':     _int(r.get('Exchange Active')),
                'exchange_inactive':   _int(r.get('Exchange Inactive')),
                'onedrive_active':     _int(r.get('OneDrive Active')),
                'onedrive_inactive':   _int(r.get('OneDrive Inactive')),
                'sharepoint_active':   _int(r.get('SharePoint Active')),
                'sharepoint_inactive': _int(r.get('SharePoint Inactive')),
                'skype_active':        _int(r.get('Skype For Business Active')),
                'skype_inactive':      _int(r.get('Skype For Business Inactive')),
                'yammer_active':       _int(r.get('Yammer Active')),
                'yammer_inactive':     _int(r.get('Yammer Inactive')),
                'teams_active':        _int(r.get('Teams Active')),
                'teams_inactive':      _int(r.get('Teams Inactive')),
                'office365_active':    _int(r.get('Office 365 Active')),
                'office365_inactive':  _int(r.get('Office 365 Inactive')),
            })
        return out

    def fetch_activity_counts(self) -> list[dict]:
        out = []
        for r in _read(self._activity_counts_path):
            out.append({
                'report_date':         r.get('Report Date', ''),
                'report_period':       r.get('Report Period', ''),
                'report_refresh_date': r.get('Report Refresh Date', ''),
                'exchange':            _int(r.get('Exchange')),
                'onedrive':            _int(r.get('OneDrive')),
                'sharepoint':          _int(r.get('SharePoint')),
                'skype':               _int(r.get('Skype For Business')),
                'yammer':              _int(r.get('Yammer')),
                'teams':               _int(r.get('Teams')),
            })
        return out

    def fetch_active_user_counts(self) -> list[dict]:
        out = []
        for r in _read(self._active_user_counts_path):
            out.append({
                'report_date':         r.get('Report Date', ''),
                'report_period':       r.get('Report Period', ''),
                'report_refresh_date': r.get('Report Refresh Date', ''),
                'office365':           _int(r.get('Office 365')),
                'exchange':            _int(r.get('Exchange')),
                'onedrive':            _int(r.get('OneDrive')),
                'sharepoint':          _int(r.get('SharePoint')),
                'skype':               _int(r.get('Skype For Business')),
                'yammer':              _int(r.get('Yammer')),
                'teams':               _int(r.get('Teams')),
            })
        return out

    def fetch_active_users_detail(self) -> list[dict]:
        out = []
        for r in _read(self._active_users_detail_path):
            out.append({
                'user_principal_name':     r.get('User Principal Name', ''),
                'report_refresh_date':     r.get('Report Refresh Date', ''),
                'display_name':            r.get('Display Name', ''),
                'is_deleted':              _bool(r.get('Is Deleted', '')),
                'deleted_date':            r.get('Deleted Date', ''),
                'has_exchange':            _bool(r.get('Has Exchange License', '')),
                'has_onedrive':            _bool(r.get('Has OneDrive License', '')),
                'has_sharepoint':          _bool(r.get('Has SharePoint License', '')),
                'has_skype':               _bool(r.get('Has Skype For Business License', '')),
                'has_yammer':              _bool(r.get('Has Yammer License', '')),
                'has_teams':               _bool(r.get('Has Teams License', '')),
                'exchange_last_activity':  r.get('Exchange Last Activity Date', ''),
                'onedrive_last_activity':  r.get('OneDrive Last Activity Date', ''),
                'sharepoint_last_activity': r.get('SharePoint Last Activity Date', ''),
                'skype_last_activity':     r.get('Skype For Business Last Activity Date', ''),
                'yammer_last_activity':    r.get('Yammer Last Activity Date', ''),
                'teams_last_activity':     r.get('Teams Last Activity Date', ''),
                'exchange_license_date':   r.get('Exchange License Assign Date', ''),
                'onedrive_license_date':   r.get('OneDrive License Assign Date', ''),
                'sharepoint_license_date': r.get('SharePoint License Assign Date', ''),
                'skype_license_date':      r.get('Skype For Business License Assign Date', ''),
                'yammer_license_date':     r.get('Yammer License Assign Date', ''),
                'teams_license_date':      r.get('Teams License Assign Date', ''),
                'assigned_products':       r.get('Assigned Products', ''),
            })
        return out

    def fetch_proplus_platforms(self) -> list[dict]:
        out = []
        for r in _read(self._proplus_platforms_path):
            out.append({
                'report_date':         r.get('Report Date', ''),
                'report_period':       r.get('Report Period', ''),
                'report_refresh_date': r.get('Report Refresh Date', ''),
                'windows':             _int(r.get('Windows')),
                'mac':                 _int(r.get('Mac')),
                'mobile':              _int(r.get('Mobile')),
                'web':                 _int(r.get('Web')),
            })
        return out

    def fetch_proplus_counts(self) -> list[dict]:
        out = []
        for r in _read(self._proplus_counts_path):
            out.append({
                'report_date':         r.get('Report Date', ''),
                'report_period':       r.get('Report Period', ''),
                'report_refresh_date': r.get('Report Refresh Date', ''),
                'outlook':             _int(r.get('Outlook')),
                'word':                _int(r.get('Word')),
                'excel':               _int(r.get('Excel')),
                'powerpoint':          _int(r.get('PowerPoint')),
                'onenote':             _int(r.get('OneNote')),
                'teams':               _int(r.get('Teams')),
            })
        return out

    def fetch_proplus_detail(self) -> list[dict]:
        out = []
        for r in _read(self._proplus_detail_path):
            out.append({
                'user_principal_name':  r.get('User Principal Name', ''),
                'report_refresh_date':  r.get('Report Refresh Date', ''),
                'last_activation_date': r.get('Last Activation Date', ''),
                'last_activity_date':   r.get('Last Activity Date', ''),
                'report_period':        r.get('Report Period', ''),
                'windows':              _bool(r.get('Windows', '')),
                'mac':                  _bool(r.get('Mac', '')),
                'mobile':               _bool(r.get('Mobile', '')),
                'web':                  _bool(r.get('Web', '')),
                'outlook':              _bool(r.get('Outlook', '')),
                'word':                 _bool(r.get('Word', '')),
                'excel':                _bool(r.get('Excel', '')),
                'powerpoint':           _bool(r.get('PowerPoint', '')),
                'onenote':              _bool(r.get('OneNote', '')),
                'teams':                _bool(r.get('Teams', '')),
            })
        return out

    def fetch_billing_licences(self) -> list[dict]:
        out = []
        for r in _read(self._billing_licences_path):
            title = r.get('Product Title', '').strip()
            if not title:
                continue
            out.append({
                'product_title':     title,
                'total_licenses':    _int(r.get('Total Licenses')),
                'expired_licenses':  _int(r.get('Expired Licenses')),
                'assigned_licenses': _int(r.get('Assigned licenses')),
                'status_message':    r.get('Status Message', ''),
            })
        return out
