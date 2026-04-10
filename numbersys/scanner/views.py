# scanner/views.py

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.conf import settings
from .models import Document, DocumentRow, Winner
from .forms import DocumentUploadForm, DocumentRowFormSet, CommissionForm, WinnerForm
from .extractor import extract_data_with_qwen

from .forms import (
    DocumentUploadForm,
    DocumentRowFormSet,
    StaffUserCreateForm,
    StaffUserEditForm,
)
from .models import Document, DocumentRow, UserProfile


def home(request):
    # Default page for website root "/"
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect("login")


@login_required
def dashboard(request):
    profile = request.user.profile
    documents = Document.objects.filter(owner=request.user).order_by("-created_at")[:20]
    return render(request, "scanner/dashboard.html", {"profile": profile, "documents": documents})


# --------------------------
# Staff: Users management
# --------------------------

@staff_member_required
def staff_users(request):
    users = User.objects.select_related("profile").order_by("username")
    return render(request, "scanner/staff_users.html", {"users": users})


@staff_member_required
def staff_user_create(request):
    if request.method == "POST":
        form = StaffUserCreateForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = User.objects.create_user(
                    username=form.cleaned_data["username"],
                    password=form.cleaned_data["password1"],
                )
                user.is_active = form.cleaned_data["is_active"]
                user.save(update_fields=["is_active"])

                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.scan_credits_total = form.cleaned_data["scan_credits_total"]
                profile.scan_credits_used = 0
                profile.save(update_fields=["scan_credits_total", "scan_credits_used"])

            messages.success(request, "User created successfully.")
            return redirect("staff_users")
    else:
        form = StaffUserCreateForm()

    return render(
        request,
        "scanner/staff_user_form.html",
        {"form": form, "mode": "create", "title": "Create User"},
    )


@staff_member_required
def staff_user_edit(request, user_id: int):
    user = get_object_or_404(User, pk=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=user)

    if request.method == "POST":
        form = StaffUserEditForm(request.POST, user_obj=user)
        if form.is_valid():
            with transaction.atomic():
                user.username = form.cleaned_data["username"]
                user.is_active = form.cleaned_data["is_active"]
                user.save(update_fields=["username", "is_active"])

                profile.scan_credits_total = form.cleaned_data["scan_credits_total"]
                profile.scan_credits_used = form.cleaned_data["scan_credits_used"]
                profile.save(update_fields=["scan_credits_total", "scan_credits_used"])

                p1 = form.cleaned_data.get("new_password1")
                if p1:
                    user.set_password(p1)
                    user.save(update_fields=["password"])
                    messages.info(request, "Password was updated (user must login again).")

            messages.success(request, "User updated successfully.")
            return redirect("staff_users")
    else:
        form = StaffUserEditForm(
            initial={
                "username": user.username,
                "is_active": user.is_active,
                "scan_credits_total": profile.scan_credits_total,
                "scan_credits_used": profile.scan_credits_used,
            },
            user_obj=user,
        )

    return render(
        request,
        "scanner/staff_user_form.html",
        {
            "form": form,
            "mode": "edit",
            "title": f"Edit User: {user.username}",
            "target_user": user,
        },
    )


# --------------------------
# Documents: Upload + Detail
# --------------------------

@login_required
def document_upload(request):
    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.owner = request.user
            doc.status = Document.Status.UPLOADED
            doc.save()
            messages.success(request, "Document uploaded successfully.")
            return redirect("document_detail", doc_id=doc.id)
    else:
        form = DocumentUploadForm()

    return render(request, "scanner/document_upload.html", {"form": form})


@login_required
def document_detail(request, doc_id: int):
    doc = get_object_or_404(Document, pk=doc_id, owner=request.user)

    rows_left_qs = doc.rows.filter(side=DocumentRow.Side.LEFT).order_by("row_index")
    rows_right_qs = doc.rows.filter(side=DocumentRow.Side.RIGHT).order_by("row_index")

    formset_left = DocumentRowFormSet(queryset=rows_left_qs, prefix="left")
    formset_right = DocumentRowFormSet(queryset=rows_right_qs, prefix="right")

    commission_form = CommissionForm(initial={
        "commission_type": doc.commission_type,
        "commission_value": doc.commission_value,
    })
    winner_form = WinnerForm()

    # Winner numbers for highlighting rows
    winner_numbers = set(doc.winners.values_list("winner_number", flat=True))

    if request.method == "POST":
        action = request.POST.get("action", "")

        # ---- Save/Edit table rows ----
        if action in ["save_rows", "verify_rows"] and doc.status in [Document.Status.EXTRACTED, Document.Status.VERIFIED]:
            formset_left = DocumentRowFormSet(request.POST, queryset=rows_left_qs, prefix="left")
            formset_right = DocumentRowFormSet(request.POST, queryset=rows_right_qs, prefix="right")

            if formset_left.is_valid() and formset_right.is_valid():
                formset_left.save()
                formset_right.save()

                issues = validate_document_rows(doc)
                recompute_document_financials(doc)

                if action == "verify_rows":
                    if issues == 0:
                        doc.status = Document.Status.VERIFIED
                        doc.save(update_fields=["status"])
                        messages.success(request, "Verified successfully.")
                    else:
                        messages.error(request, f"Cannot verify. Fix {issues} issue(s) highlighted in red.")
                else:
                    messages.success(request, "Saved. Issues (if any) are highlighted.")

                return redirect("document_detail", doc_id=doc.id)

            messages.error(request, "Please correct invalid inputs (numbers only).")
            return redirect("document_detail", doc_id=doc.id)

        # ---- Update commission ----
        if action == "update_commission" and doc.status in [Document.Status.EXTRACTED, Document.Status.VERIFIED]:
            commission_form = CommissionForm(request.POST)
            if commission_form.is_valid():
                doc.commission_type = commission_form.cleaned_data["commission_type"]
                doc.commission_value = commission_form.cleaned_data["commission_value"]
                doc.save(update_fields=["commission_type", "commission_value"])
                recompute_document_financials(doc)
                messages.success(request, "Commission updated.")
            else:
                messages.error(request, "Invalid commission inputs.")
            return redirect("document_detail", doc_id=doc.id)

        # ---- Add winner ----
        if action == "add_winner" and doc.status in [Document.Status.EXTRACTED, Document.Status.VERIFIED]:
            winner_form = WinnerForm(request.POST)
            if winner_form.is_valid():
                Winner.objects.create(
                    document=doc,
                    winner_number=winner_form.cleaned_data["winner_number"],
                    prize_amount=winner_form.cleaned_data["prize_amount"],
                )
                recompute_document_financials(doc)
                messages.success(request, "Winner added.")
            else:
                messages.error(request, "Invalid winner inputs.")
            return redirect("document_detail", doc_id=doc.id)

        # ---- Delete winner ----
        if action == "delete_winner" and doc.status in [Document.Status.EXTRACTED, Document.Status.VERIFIED]:
            wid = request.POST.get("winner_id")
            Winner.objects.filter(document=doc, id=wid).delete()
            recompute_document_financials(doc)
            messages.success(request, "Winner removed.")
            return redirect("document_detail", doc_id=doc.id)

        # ---- Finalize ----
        if action == "finalize" and doc.status == Document.Status.VERIFIED:
            # must be clean
            if doc.issues_count == 0:
                recompute_document_financials(doc)
                doc.status = Document.Status.FINALIZED
                doc.save(update_fields=["status"])
                messages.success(request, "Document finalized. Values locked.")
            else:
                messages.error(request, "Cannot finalize: document still has issues.")
            return redirect("document_detail", doc_id=doc.id)

    # Always compute latest snapshot before display
    recompute_document_financials(doc)

    # CSV for copy box
    def build_csv(rows):
        lines = []
        for r in rows:
            if r.number is None and r.first_price is None and r.second_price is None:
                continue
            n = "" if r.number is None else str(r.number)
            f = "" if r.first_price is None else str(r.first_price)
            s = "" if r.second_price is None else str(r.second_price)
            lines.append(f"{n},{f},{s}")
        return "\n".join(lines)

    csv_left = build_csv(list(rows_left_qs))
    csv_right = build_csv(list(rows_right_qs))

    # Get extracted data from session if available
    extracted_data = request.session.pop('extracted_data', None)

    # Build preview rows for a 10-column ledger (S.N + N.1/F/S + N.2/F/S + N.3/F/S)
    raw_preview_rows = extracted_data if isinstance(extracted_data, list) else []
    preview_rows = []
    if raw_preview_rows:
        preview_row_count = max(25, len(raw_preview_rows))
        for i in range(preview_row_count):
            row = raw_preview_rows[i] if i < len(raw_preview_rows) and isinstance(raw_preview_rows[i], dict) else {}
            preview_rows.append({
                "S": row.get("S", ""),
                "N1": row.get("N1", ""),
                "F1": row.get("F1", ""),
                "S1": row.get("S1", ""),
                "N2": row.get("N2", ""),
                "F2": row.get("F2", ""),
                "S2": row.get("S2", ""),
                "N3": row.get("N3", ""),
                "F3": row.get("F3", ""),
                "S3": row.get("S3", ""),
            })

    # Pair left/right form rows so the editor table mirrors the physical ledger in one grid
    left_forms = list(formset_left)
    right_forms = list(formset_right)
    ledger_form_row_count = max(25, len(left_forms), len(right_forms))
    ledger_form_rows = []
    for i in range(ledger_form_row_count):
        extracted_row = raw_preview_rows[i] if i < len(raw_preview_rows) and isinstance(raw_preview_rows[i], dict) else {}
        ledger_form_rows.append({
            "left": left_forms[i] if i < len(left_forms) else None,
            "right": right_forms[i] if i < len(right_forms) else None,
            "n3": extracted_row.get("N3", ""),
            "f3": extracted_row.get("F3", ""),
            "s3": extracted_row.get("S3", ""),
        })

    return render(request, "scanner/document_detail.html", {
        "doc": doc,
        "profile": request.user.profile,
        "formset_left": formset_left,
        "formset_right": formset_right,
        "commission_form": commission_form,
        "winner_form": winner_form,
        "winners": doc.winners.all().order_by("-created_at"),
        "winner_numbers": winner_numbers,
        "csv_left": csv_left,
        "csv_right": csv_right,
        "extracted_data": extracted_data,
        "preview_rows": preview_rows,
        "ledger_form_rows": ledger_form_rows,
    })



@login_required
def document_start_extraction(request, doc_id: int):
    if request.method != "POST":
        return redirect("document_detail", doc_id=doc_id)

    doc = get_object_or_404(Document, pk=doc_id, owner=request.user)
    profile = request.user.profile

    if doc.status not in [Document.Status.UPLOADED, Document.Status.FAILED]:
        messages.info(request, "Extraction already started or document not in uploaded state.")
        return redirect("document_detail", doc_id=doc_id)

    if profile.scan_credits_remaining <= 0:
        messages.error(request, "No scan credits remaining. Contact admin.")
        return redirect("document_detail", doc_id=doc_id)

    with transaction.atomic():
        profile.scan_credits_used += 1
        profile.save(update_fields=["scan_credits_used"])

        doc.status = Document.Status.PROCESSING
        doc.save(update_fields=["status"])

        # ✅ Call the LLM extractor
        image_path = doc.file.path
        api_key = settings.QWEN_API_KEY
        extracted_data = extract_data_with_qwen(image_path, api_key)

        # Create rows (only if not already created)
        if not doc.rows.exists():
            for i in range(1, 31):  # 1..30
                DocumentRow.objects.create(
                    document=doc,
                    side=DocumentRow.Side.LEFT,
                    row_index=i,
                    serial=i,  # default serial equals row index
                )
                DocumentRow.objects.create(
                    document=doc,
                    side=DocumentRow.Side.RIGHT,
                    row_index=i,
                    serial=None,
                )

        # ✅ Populate rows with extracted data if successful
        if extracted_data:
            for idx, row_data in enumerate(extracted_data, start=1):
                if idx > 30:
                    break
                
                # LEFT SIDE
                left_row = doc.rows.get(side=DocumentRow.Side.LEFT, row_index=idx)
                left_row.number = row_data.get("N1")
                left_row.first_price = row_data.get("F1")
                left_row.second_price = row_data.get("S1")
                left_row.save(update_fields=["number", "first_price", "second_price"])
                
                # RIGHT SIDE
                right_row = doc.rows.get(side=DocumentRow.Side.RIGHT, row_index=idx)
                right_row.number = row_data.get("N2")
                right_row.first_price = row_data.get("F2")
                right_row.second_price = row_data.get("S2")
                right_row.save(update_fields=["number", "first_price", "second_price"])

            # Store extracted data in session for display
            request.session['extracted_data'] = extracted_data
            doc.status = Document.Status.EXTRACTED
            doc.error_message = ""
            doc.save(update_fields=["status", "error_message"])
            messages.success(request, "Extraction successful! Review the data below.")
        else:
            doc.status = Document.Status.FAILED
            doc.error_message = "Extractor could not parse a valid table from the model response."
            doc.save(update_fields=["status", "error_message"])
            messages.error(request, "Extraction failed. Please try again.")

    # Validate to compute initial issues
    validate_document_rows(doc)

    return redirect("document_detail", doc_id=doc.id)


# --------------------------
# Validation logic
# --------------------------

def validate_document_rows(doc: Document) -> int:
    """
    Sets flags on rows and updates doc.needs_review/doc.issues_count.
    Returns total issues_count.
    """
    issues = 0

    rows_left = list(doc.rows.filter(side=DocumentRow.Side.LEFT).order_by("row_index"))
    rows_right = list(doc.rows.filter(side=DocumentRow.Side.RIGHT).order_by("row_index"))

    def reset_flags(r: DocumentRow):
        r.serial_flag = DocumentRow.Flag.OK
        r.number_flag = DocumentRow.Flag.OK
        r.first_flag = DocumentRow.Flag.OK
        r.second_flag = DocumentRow.Flag.OK

    def flag_if_missing_or_invalid(r: DocumentRow, field_name: str, required: bool):
        nonlocal issues
        val = getattr(r, field_name)
        flag_attr = {
            "serial": "serial_flag",
            "number": "number_flag",
            "first_price": "first_flag",
            "second_price": "second_flag",
        }[field_name]

        if val is None:
            if required:
                setattr(r, flag_attr, DocumentRow.Flag.MISSING)
                issues += 1
        else:
            # numeric fields are already cast by forms; just ensure non-negative
            if isinstance(val, int) and val < 0:
                setattr(r, flag_attr, DocumentRow.Flag.INVALID)
                issues += 1

    # LEFT: serial required and must equal row_index
    for r in rows_left:
        reset_flags(r)

        if r.serial is None:
            r.serial_flag = DocumentRow.Flag.MISSING
            issues += 1
        elif r.serial != r.row_index:
            r.serial_flag = DocumentRow.Flag.INVALID
            issues += 1

        any_filled = any(
            [
                r.number is not None,
                r.first_price is not None,
                r.second_price is not None,
            ]
        )

        if any_filled:
            flag_if_missing_or_invalid(r, "number", required=True)
            flag_if_missing_or_invalid(r, "first_price", required=True)
            flag_if_missing_or_invalid(r, "second_price", required=True)
        else:
            flag_if_missing_or_invalid(r, "number", required=False)
            flag_if_missing_or_invalid(r, "first_price", required=False)
            flag_if_missing_or_invalid(r, "second_price", required=False)

        r.save(update_fields=["serial_flag", "number_flag", "first_flag", "second_flag"])

    # RIGHT: no serial requirement; same “all-or-nothing” rule
    for r in rows_right:
        reset_flags(r)

        any_filled = any(
            [
                r.number is not None,
                r.first_price is not None,
                r.second_price is not None,
            ]
        )

        if any_filled:
            flag_if_missing_or_invalid(r, "number", required=True)
            flag_if_missing_or_invalid(r, "first_price", required=True)
            flag_if_missing_or_invalid(r, "second_price", required=True)
        else:
            flag_if_missing_or_invalid(r, "number", required=False)
            flag_if_missing_or_invalid(r, "first_price", required=False)
            flag_if_missing_or_invalid(r, "second_price", required=False)

        r.save(update_fields=["serial_flag", "number_flag", "first_flag", "second_flag"])

    doc.issues_count = issues
    doc.needs_review = issues > 0
    doc.save(update_fields=["issues_count", "needs_review"])

    return issues


def recompute_document_financials(doc: Document) -> None:
    """
    Computes totals, commission, prize, net bill from rows + winners.
    Saves the computed snapshot fields on Document.
    """
    rows = doc.rows.all()

    total_first = 0
    total_second = 0
    for r in rows:
        if r.first_price is not None:
            total_first += int(r.first_price)
        if r.second_price is not None:
            total_second += int(r.second_price)

    grand_total = total_first + total_second

    # commission
    commission_amount = 0
    if doc.commission_type == Document.CommissionType.PERCENT:
        # percent applied on grand total
        commission_amount = int(round(grand_total * (float(doc.commission_value) / 100.0)))
    else:
        commission_amount = int(round(float(doc.commission_value)))

    total_after_commission = max(grand_total - commission_amount, 0)

    # prize total
    total_prize = 0
    for w in doc.winners.all():
        total_prize += int(w.prize_amount)

    net_bill = int(total_after_commission) - int(total_prize)

    doc.total_first = total_first
    doc.total_second = total_second
    doc.grand_total = grand_total
    doc.commission_amount = max(commission_amount, 0)
    doc.total_after_commission = total_after_commission
    doc.total_prize = total_prize
    doc.net_bill = net_bill
    doc.save(update_fields=[
        "total_first", "total_second", "grand_total",
        "commission_amount", "total_after_commission",
        "total_prize", "net_bill",
    ])


# Reports
@login_required
def reports_summary(request):
    docs = Document.objects.filter(owner=request.user, status__in=[Document.Status.VERIFIED, Document.Status.FINALIZED])

    total_grand = sum(d.grand_total for d in docs)
    total_commission = sum(d.commission_amount for d in docs)
    total_after = sum(d.total_after_commission for d in docs)
    total_prize = sum(d.total_prize for d in docs)
    total_net = sum(d.net_bill for d in docs)

    return render(request, "scanner/reports_summary.html", {
        "docs": docs.order_by("-created_at"),
        "total_grand": total_grand,
        "total_commission": total_commission,
        "total_after": total_after,
        "total_prize": total_prize,
        "total_net": total_net,
    })
