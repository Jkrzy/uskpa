import datetime

from django import forms
from django.contrib.auth import get_user_model

from .models import Certificate, Licensee

User = get_user_model()

DATE_ATTRS = {'type': 'date', 'placeholder': 'mm/dd/yyyy'}


class USWDSRadioSelect(forms.RadioSelect):
    option_template_name = 'uswds/radio_options.html'


class UserModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.get_full_name()


class LicenseeCertificateForm(forms.ModelForm):
    date_of_issue = forms.DateField(
        widget=forms.DateInput(attrs=DATE_ATTRS))
    date_of_expiry = forms.DateField(widget=forms.DateInput(attrs={'readonly': 'readonly',
                                                                   'placeholder': 'Auto-filled from Date of Issue'}))
    SUCCESS_MSG = "Thank you! Your certificate has been successfully issued."

    def __init__(self, *args, **kwargs):
        """
        All fields are required for Licensee to complete certificate
        """
        self.editable = kwargs.pop('editable', True)
        super().__init__(*args, **kwargs)
        self.expiry_days = Certificate.get_expiry_days()
        self.date_expiry_invalid = f'Date of Expiry must be {self.expiry_days} days after Date of Issue'
        self.fields['date_of_expiry'].label = f"Date of Expiry ({self.expiry_days} days from date issued)"

        for field in self.fields:
            self.fields[field].required = True
            if not self.editable:
                self.fields[field].disabled = True

    class Meta:
        model = Certificate
        fields = ('aes', 'country_of_origin', 'shipped_value', 'exporter', 'exporter_address',
                  'number_of_parcels', 'consignee', 'consignee_address', 'carat_weight', 'harmonized_code',
                  'date_of_issue', 'date_of_expiry', 'attested', 'port_of_export')

    def clean(self):
        date_of_issue = self.cleaned_data.get('date_of_issue')
        date_of_expiry = self.cleaned_data.get('date_of_expiry')

        # Date of expiry must be CertificateConfig.expiry_days after date of issue
        if date_of_issue and date_of_expiry:
            delta = date_of_expiry - date_of_issue
            if delta.days != self.expiry_days:
                self.add_error('date_of_expiry', self.date_expiry_invalid)

    def save(self, commit=True):
        """Set status to PREPARED"""
        if commit:
            self.instance.status = Certificate.PREPARED
            self.instance.save()
        return self.instance


class CertificateRegisterForm(forms.Form):
    LIST = 'list'
    SEQUENTIAL = 'sequential'

    REGISTRATION_METHODS = ((SEQUENTIAL, 'Sequential'), (LIST, 'List'))

    licensee = forms.ModelChoiceField(queryset=Licensee.objects.all())
    contact = UserModelChoiceField(queryset=User.objects.all())
    date_of_sale = forms.DateField(
        initial=datetime.date.today, widget=forms.DateInput(attrs=DATE_ATTRS))
    registration_method = forms.ChoiceField(choices=REGISTRATION_METHODS,
                                            widget=USWDSRadioSelect(
                                                attrs={'class': 'usa-unstyled-list'}),
                                            initial=SEQUENTIAL)
    cert_from = forms.IntegerField(min_value=0, required=False, label='From')
    cert_to = forms.IntegerField(min_value=1, required=False, label='To')
    cert_list = forms.CharField(required=False, label='Certificate ID list')
    payment_method = forms.ChoiceField(
        choices=Certificate.PAYMENT_METHOD_CHOICES)
    payment_amount = forms.DecimalField(max_digits=10, decimal_places=2)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.price = Certificate.get_price()
        self.fields[
            'payment_amount'].label = f'Payment amount (Certificate price: ${self.price})'

        data = kwargs.get('data', None)
        if data:
            licensee = data.get('licensee', None)
            contact = data.get('contact', None)
            if licensee:
                self.fields['contact'].queryset = User.objects.filter(
                    profile__licensees__in=[licensee])
            if contact:
                self.fields['contact'].initial = contact
        else:
            self.fields['contact'].choices = [
                ('', self.fields['contact'].empty_label)]
        self.fields['cert_from'].initial = Certificate.next_available_number()

    def clean(self):
        """Validations requiring cross-field checks"""
        cleaned_data = super().clean()
        licensee = cleaned_data.get("licensee")
        contact = cleaned_data.get("contact")
        cert_from = cleaned_data.get("cert_from")
        cert_to = cleaned_data.get("cert_to")
        cert_list = cleaned_data.get("cert_list")
        payment_aount = cleaned_data.get("payment_amount")
        self.method = cleaned_data.get('registration_method')

        if licensee and contact:
            if not contact.profile.licensees.filter(id=licensee.id).exists():
                raise forms.ValidationError(
                    "Contact is not associated with selected Licensee"
                )

        if self.method == self.LIST and not cert_list:
            self.add_error('cert_list', 'List of ID values required.')
            raise forms.ValidationError(
                "Certificate List must be provided when List method is selected.")

        if self.method == self.SEQUENTIAL and (not cert_from or not cert_to):
            raise forms.ValidationError(
                "Certificate To and From must be provided when Sequential method is selected.")

        if cert_from and cert_to:
            if cert_from > cert_to:
                self.add_error('cert_from', 'Value must be less than "To"')
                self.add_error(
                    'cert_to', 'Value must be greater than or equal to "From"')
                raise forms.ValidationError(
                    "Certificate 'To' value must be greater than or equal to 'From' value.")

        requested_certs = self.get_cert_list()
        """payment amount matches expected value"""
        requested_cert_count = len(requested_certs)
        expected_payment = requested_cert_count * self.price
        if payment_aount != expected_payment:
            raise forms.ValidationError(
                f"A payment of ${expected_payment} is required. ({requested_cert_count} requested certificates @ ${self.price} per certificate.)")

        # Check for existence of requested certficates
        existing = Certificate.objects.filter(
            number__in=requested_certs).exists()
        if existing:
            raise forms.ValidationError(
                f"""At least one of the requested certificates already exists in the database.
                    The next available certificate number is: {Certificate.next_available_number()}""")

    def get_cert_list(self):
        """return list of certificates to generate"""
        certs = []
        if self.method == self.SEQUENTIAL:
            start = self.cleaned_data['cert_from']
            end = self.cleaned_data['cert_to']
            certs = [i for i in range(start, end+1)]
        elif self.method == self.LIST:
            cert_list = self.cleaned_data['cert_list'].split(',')
            certs = [int(cert_number.strip()[2:]) for cert_number in cert_list]
        return certs


class StatusUpdateForm(forms.ModelForm):
    date = forms.DateField(required=True)
    next_status = forms.IntegerField(required=True)

    UNEXPECTED_STATUS = 'Unable to update status, please reload the page and try again.'
    INTRANSIT_DATE = "The In-Transit date must be on or after the certificate's date of issue (%s)."
    DELIVERY_DATE = "The Delivered date must be on or after the certificate's date of shipment (%s)."
    NOT_AVAILABLE = "This certificate has already been issued."
    SUCCESS_MSG = 'Certificate status has been succesfully updated.'

    def __init__(self, *args, **kwargs):
        self.editable = kwargs.pop('editable', False)
        super().__init__(*args, **kwargs)

    class Meta:
        model = Certificate
        fields = ("date", 'next_status')

    def clean(self):
        """Dates must be ordered"""
        if 'attested' in self.data.keys():
            # Certificate issue form was submitted
            # We're expecting only status changes
            # Likely certificate was issued while form was being completed.
            raise forms.ValidationError(self.NOT_AVAILABLE)

        cleaned_data = super().clean()
        date = cleaned_data.get('date')
        new_status = cleaned_data.get('next_status')

        if new_status != self.instance.next_status_value:
            raise forms.ValidationError(self.UNEXPECTED_STATUS)

        if new_status == Certificate.INTRANSIT:
            if date < self.instance.date_of_issue:
                raise forms.ValidationError(
                    self.INTRANSIT_DATE % self.instance.date_of_issue)

        if new_status == Certificate.DELIVERED:
            if date < self.instance.date_of_shipment:
                raise forms.ValidationError(
                    self.DELIVERY_DATE % self.instance.date_of_shipment)

    def save(self):
        """Set our new status and associated date"""
        date = self.cleaned_data['date']
        new_status = self.cleaned_data['next_status']
        self.instance.status = new_status

        if new_status == Certificate.INTRANSIT:
            self.instance.date_of_shipment = date
        if new_status == Certificate.DELIVERED:
            self.instance.date_of_delivery = date

        self.instance.save()
        return self.instance


class VoidForm(forms.ModelForm):
    OTHER_CHOICE = 'Other'
    void = forms.BooleanField(help_text="I wish to void this certificate.")
    reason = forms.ChoiceField(choices=[])
    notes = forms.CharField(widget=forms.Textarea(), required=False)

    SUCCESS_MSG = "Certificate has been successfully voided."
    REASON_REQUIRED = "Please provide a reason for this action."

    class Meta:
        model = Certificate
        fields = ("void", "notes")

    def __init__(self, *args, **kwargs):
        """Set void reason choices"""
        choices = [(reason.value, reason.value)
                   for reason in Certificate.get_void_reasons()]
        choices.append(('Other', 'Other'))
        super().__init__(*args, **kwargs)
        self.fields['reason'].choices = choices

    def clean(self):
        reason = self.cleaned_data.get('reason')
        notes = self.cleaned_data.get('notes')

        if reason == self.OTHER_CHOICE and not notes:
            raise forms.ValidationError(self.REASON_REQUIRED)

    def save(self):
        """Set status to void"""
        cert = self.instance
        cert.status = Certificate.VOID
        cert.void = True
        cert.notes = self.cleaned_data['notes'] or self.cleaned_data['reason']
        cert.date_voided = datetime.date.today()
        cert.save()
        return cert
