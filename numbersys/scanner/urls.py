from django.urls import path
from .views import (
    home, dashboard,
    document_upload, document_detail, document_start_extraction, staff_users, staff_user_create, staff_user_edit, reports_summary
)

urlpatterns = [
    path("", home, name="home"),   
    path("dashboard/", dashboard, name="dashboard"),
    path("staff/users/", staff_users, name="staff_users"),  # ✅ staff-only dashboard
    path("staff/users/create/", staff_user_create, name="staff_user_create"),
    path("staff/users/<int:user_id>/edit/", staff_user_edit, name="staff_user_edit"),
    path("documents/upload/", document_upload, name="document_upload"),
    path("documents/<int:doc_id>/", document_detail, name="document_detail"),
    path("documents/<int:doc_id>/extract/", document_start_extraction, name="document_start_extraction"),
    path("reports/", reports_summary, name="reports_summary"),

]
