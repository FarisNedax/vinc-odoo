var isSubmitting = false; // Globally accessible
var isSubmittingReview = false; // For review submissions
var isSubmittingServiceRequest = false; // For service request submissions
// Keep native alert behavior in production

$(document).ready(function() {
    // Honeypot: off-screen field people never fill; form-filling bots do.
    $('#leadForm, #reviewForm, #serviceRequestForm').each(function() {
        if (!$(this).find('[name="company_fax"]').length) {
            $(this).append('<input type="text" name="company_fax" tabindex="-1" autocomplete="off" aria-hidden="true" style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0;"/>');
        }
    });

    console.log('Binding lead submission button handler');
    
    // Initialize intl-tel-input country code picker
    function initPhoneInputField(phoneInput) {
        if (!phoneInput) return;
        
        try {
            var $phoneInput = $(phoneInput);
            // Check if already initialized
            if ($phoneInput.parent().hasClass('iti') || $phoneInput.parent().hasClass('intl-tel-input')) {
                console.log('Phone input already initialized');
                return;
            }
            
            console.log('Initializing intl-tel-input on phone field');
                        var iti = window.intlTelInput(phoneInput, {
                            initialCountry: "us",
                            preferredCountries: ["us", "gb", "ca", "au"],
                            utilsScript: "https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.19/js/utils.js",
                            separateDialCode: true,
                            nationalMode: false,
                            autoPlaceholder: "polite",
                            formatOnDisplay: true
                        });
            
            console.log('intl-tel-input initialized successfully');
            
            // Fix z-index for country dropdown to appear above modals
            // Set z-index immediately and also on click
            setTimeout(function() {
                var countryList = document.querySelector('.iti__country-list');
                if (countryList) {
                    countryList.style.zIndex = '9999';
                }
            }, 100);
            
            // Watch for flag click to open dropdown
            var flagContainer = phoneInput.closest('.iti') || phoneInput.parentElement;
            if (flagContainer) {
                var selectedFlag = flagContainer.querySelector('.iti__selected-flag');
                if (selectedFlag) {
                    selectedFlag.addEventListener('click', function() {
                        setTimeout(function() {
                            var countryList = document.querySelector('.iti__country-list');
                            if (countryList) {
                                countryList.style.zIndex = '9999';
                            }
                        }, 50);
                    });
                }
            }
            
            // Update hidden field with full number when phone changes
            phoneInput.addEventListener('input', function() {
                try {
                    var fullNumber = iti.getNumber();
                    // Check if this is the service request phone field
                    if (phoneInput.id === 'serviceRequestPhone') {
                        $('#serviceRequestPhoneFull').val(fullNumber);
                    } else {
                        $('#phone_full').val(fullNumber);
                    }
                } catch(e) {
                    console.log('Error getting phone number:', e);
                }
            });
            
            // Also update on country change
            phoneInput.addEventListener('countrychange', function() {
                try {
                    var fullNumber = iti.getNumber();
                    // Check if this is the service request phone field
                    if (phoneInput.id === 'serviceRequestPhone') {
                        $('#serviceRequestPhoneFull').val(fullNumber);
                    } else {
                        $('#phone_full').val(fullNumber);
                    }
                } catch(e) {
                    console.log('Error getting phone number on country change:', e);
                }
            });
        } catch(e) {
            console.error('Error initializing intl-tel-input:', e);
        }
    }
    
    function initPhoneInput() {
        // Wait for library to load
        if (typeof window.intlTelInput === 'undefined') {
            console.log('Waiting for intl-tel-input library...');
            setTimeout(initPhoneInput, 200);
            return;
        }
        
        console.log('intl-tel-input library loaded');
        
        // Try to initialize immediately if phone field exists
        var phoneInput = document.querySelector("#phone");
        if (phoneInput) {
            initPhoneInputField(phoneInput);
        }
        
        // Also initialize when modal is shown (in case field wasn't in DOM yet)
        $(document).off('shown.bs.modal', '#leadModal').on('shown.bs.modal', '#leadModal', function() {
            console.log('Modal shown, checking phone input');
            var phoneInput = document.querySelector("#phone");
            if (phoneInput) {
                initPhoneInputField(phoneInput);
                // Fix z-index for country dropdown
                setTimeout(function() {
                    var countryList = document.querySelector('#leadModal .iti__country-list');
                    if (countryList) {
                        countryList.style.zIndex = '9999';
                    }
                }, 100);
            } else {
                console.log('Phone input field not found in modal');
            }
        });
        
        // Watch for country dropdown opening and fix z-index dynamically
        $(document).on('click', '#leadModal .iti__selected-flag, #serviceRequestModal .iti__selected-flag', function() {
            setTimeout(function() {
                var countryList = document.querySelector('.iti__country-list');
                if (countryList) {
                    countryList.style.zIndex = '9999';
                }
            }, 50);
        });
        
        // Use MutationObserver to watch for country list appearing in DOM
        var observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.addedNodes.length) {
                    mutation.addedNodes.forEach(function(node) {
                        if (node.classList && node.classList.contains('iti__country-list')) {
                            node.style.zIndex = '9999';
                        }
                        // Also check children
                        var countryList = node.querySelector && node.querySelector('.iti__country-list');
                        if (countryList) {
                            countryList.style.zIndex = '9999';
                        }
                    });
                }
            });
        });
        
        // Start observing the document body for country list additions
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
        
        // Initialize phone input for service request modal
        $(document).off('shown.bs.modal', '#serviceRequestModal').on('shown.bs.modal', '#serviceRequestModal', function() {
            console.log('Service request modal shown, checking phone input');
            
            // Wait for library to load and modal to fully render
            function tryInitServicePhone() {
                if (typeof window.intlTelInput === 'undefined') {
                    console.log('Waiting for intl-tel-input library for service request modal...');
                    setTimeout(tryInitServicePhone, 200);
                    return;
                }
                
                var phoneInput = document.querySelector("#serviceRequestPhone");
                if (phoneInput) {
                    // Check if already initialized
                    if ($(phoneInput).parent().hasClass('iti') || $(phoneInput).parent().hasClass('intl-tel-input')) {
                        console.log('Service request phone input already initialized');
                        // Still fix z-index
                        setTimeout(function() {
                            var countryList = document.querySelector('#serviceRequestModal .iti__country-list');
                            if (countryList) {
                                countryList.style.zIndex = '9999';
                            }
                        }, 100);
                        return;
                    }
                    
                    // Wait a bit for the modal to fully render
                    setTimeout(function() {
                        initPhoneInputField(phoneInput);
                        // Fix z-index after initialization
                        setTimeout(function() {
                            var countryList = document.querySelector('#serviceRequestModal .iti__country-list');
                            if (countryList) {
                                countryList.style.zIndex = '9999';
                            }
                        }, 150);
                    }, 100);
                } else {
                    console.log('Service request phone input field not found');
                }
            }
            
            tryInitServicePhone();
        });
    }
    
    // Start initialization after a short delay to ensure library is loaded
    setTimeout(function() {
        initPhoneInput();
    }, 500);
    
    // Handle phone extension dropdown - show/hide extension number field
    $(document).on('change', '#phone_extension, #phone_extension_modal', function() {
        var extensionType = $(this).val();
        var extensionField = $(this).closest('.mb-3').find('input[name="extension_number"]');
        if (extensionType && extensionType !== '') {
            extensionField.show();
        } else {
            extensionField.hide().val('');
        }
    });
    
    // Handle inline form submissions (non-modal forms) - combine phone + extension before submit
    $(document).on('submit', 'form.lead-form', function(e) {
        var $form = $(this);
        var $phoneInput = $form.find('input[name="phone"]');
        var $extensionSelect = $form.find('select[name="phone_extension"]');
        var $extensionNumber = $form.find('input[name="extension_number"]');
        
        if ($phoneInput.length && $extensionSelect.length && $extensionNumber.length) {
            var phoneNumber = $phoneInput.val();
            var extensionType = $extensionSelect.val();
            var extensionNumber = $extensionNumber.val();
            
            if (phoneNumber && extensionType && extensionNumber) {
                phoneNumber = phoneNumber + ' ' + extensionType + ' ' + extensionNumber;
                $phoneInput.val(phoneNumber);
            }
        }
    });
    
    // Reset form when modal is closed
    $('#leadModal').on('hidden.bs.modal', function() {
        $('#leadForm').show();
        $('#successMessage').hide();
        $('#leadForm')[0].reset();
        $('#extension_number').hide();
        isSubmitting = false;
    });

    // Initialize review modal when it's shown
    $('#reviewModal').on('shown.bs.modal', function() {
        console.log('Review modal opened');
        
        // Initialize stars to 5 by default
        $('#reviewRating').val('5');
        $('.star').each(function() {
            $(this).html('&#9734;');
        });
        $('.star').slice(0, 5).each(function() {
            $(this).html('&#9733;');
        });
    });

    // Reset review form when modal is closed
    $('#reviewModal').on('hidden.bs.modal', function() {
        $('#reviewForm').show();
        $('#reviewSuccessMessage').hide();
        $('#reviewForm')[0].reset();
        // Reset stars to default (5 stars)
        $('#reviewRating').val('5');
        $('.star').each(function() {
            $(this).html('&#9734;');
        });
        $('.star').slice(0, 5).each(function() {
            $(this).html('&#9733;');
        });
        isSubmittingReview = false;
    });

    // Star rating interaction - use event delegation
    $(document).on('click', '.star', function() {
        var rating = $(this).data('rating');
        console.log('Star clicked, rating:', rating);
        $('#reviewRating').val(rating);
        
        // Update star display
        $('.star').each(function() {
            $(this).html('&#9734;'); // Empty star
        });
        $('.star').slice(0, rating).each(function() {
            $(this).html('&#9733;'); // Filled star
        });
    });

    // Star rating hover effect - use event delegation
    $(document).on('mouseenter', '.star', function() {
        var rating = $(this).data('rating');
        $('.star').each(function() {
            $(this).html('&#9734;');
        });
        $('.star').slice(0, rating).each(function() {
            $(this).html('&#9733;');
        });
    });

    $(document).on('mouseleave', '.star-rating', function() {
        var currentRating = $('#reviewRating').val();
        $('.star').each(function() {
            $(this).html('&#9734;');
        });
        $('.star').slice(0, currentRating).each(function() {
            $(this).html('&#9733;');
        });
    });

    $('#submitLeadBtn').off('click').on('click', function(event) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        if (isSubmitting) {
            console.log('Submission already in progress, aborting');
            return false;
        }

        isSubmitting = true;
        var submitButton = $(this);
        var originalHTML = submitButton.html();
        submitButton.prop('disabled', true);
        // Use text() then append spinner to avoid HTML escaping issues
        var originalText = submitButton.text().trim();
        submitButton.empty().html('<i class="fa fa-spinner fa-spin"></i> Submitting...');

        // Retrieve lead_tag_ids from the hidden input and convert to an array of integers
        var leadTagIdsValue = $('#leadTagIds').val();
        var leadTagIds = leadTagIdsValue ? leadTagIdsValue.split(',').map(function(id) { 
            return parseInt(id.trim(), 10); 
        }) : [];

        // Get full phone number with country code from intl-tel-input
        var phoneNumber = '';
        try {
            if (typeof window.intlTelInput !== 'undefined' && $('#phone').length) {
                var phoneInput = $('#phone')[0];
                if (phoneInput && window.intlTelInputGlobals && window.intlTelInputGlobals.getInstance) {
                    var iti = window.intlTelInputGlobals.getInstance(phoneInput);
                    if (iti) {
                        phoneNumber = iti.getNumber();
                    }
                }
            }
            // Fallback to hidden field or direct input value
            if (!phoneNumber) {
                phoneNumber = $('#phone_full').val() || $('#phone').val() || '';
            }
        } catch(e) {
            console.log('Error getting phone number:', e);
            phoneNumber = $('#phone_full').val() || $('#phone').val() || '';
        }
        
        var formData = {
            contact_name: $('#fullName').val(),
            email_from: $('#email').val(),
            phone: phoneNumber,
            partner_id: parseInt($('#partnerId').val(), 10),
            description: $('#notes').val(),
            lead_tag_ids: leadTagIds, // Include the array of tag IDs
            company_fax: $('#leadForm [name="company_fax"]').val(),
        };

        console.log('Submitting data:', formData);

        $.ajax({
            url: '/create_lead',
            type: 'POST',
            contentType: 'application/json',
            dataType: 'json', // Ensure the response is parsed as JSON
            data: JSON.stringify(formData),
            beforeSend: function() {
                console.log('Sending request to server');
            },
            success: function(response) {
                console.log("Full response:", response);
                console.log("Response type:", typeof response);
                
                // Handle both direct response and wrapped response formats
                var result = response.result || response;
                console.log("Result:", result);
                console.log("Status:", result.status);
                console.log("Message received:", result.message);

                if (result.status === 'success') {
                    // Show success message
                    $('#successMessage').text(result.message).show();
                    // Hide the form after successful submission
                    $('#leadForm').hide();
                    
                    // Auto-close the modal after 1.5 seconds
                    setTimeout(function() {
                        $('#leadModal').modal('hide');
                        // Reset the form and show it again for next use
                        $('#leadForm').show();
                        $('#successMessage').hide();
                        $('#leadForm')[0].reset();
                    }, 1500);
                } else {
                    $('#successMessage').text(result.message || 'Unknown error occurred').show();
                }
            },
            error: function(xhr, status, error) {
                console.log('Error during request:', error);
                console.log('Response text:', xhr.responseText);
                
                var errorMessage = 'An error occurred. Please try again.';
                try {
                    var response = JSON.parse(xhr.responseText);
                    if (response.message) {
                        errorMessage = response.message;
                    }
                } catch (e) {
                    // If response is not JSON, use default message
                }
                
                $('#successMessage').text(errorMessage).show();
            },
            complete: function() {
                console.log('AJAX request complete');
                submitButton.prop('disabled', false);
                submitButton.html(originalHTML);
                isSubmitting = false;
            }
        });
        
        return false; // Ensure form submission is completely prevented
    });

    // Prevent review form from submitting normally
    $(document).on('submit', '#reviewForm', function(event) {
        event.preventDefault();
        event.stopPropagation();
        return false;
    });
    
    // Review form submission handler - use event delegation
    $(document).on('click', '#submitReviewBtn', function(event) {
        console.log('Submit review button clicked');
        event.preventDefault();
        event.stopPropagation();
        // Don't use stopImmediatePropagation here to allow other handlers if needed

        if (isSubmittingReview) {
            console.log('Review submission already in progress, aborting');
            return false;
        }

        // Validate form fields
        var reviewerName = $('#reviewerName').val();
        var rating = $('#reviewRating').val();
        var reviewText = $('#reviewText').val();
        
        if (!reviewerName || !rating || !reviewText) {
            alert('Please fill in all required fields.');
            return false;
        }

        isSubmittingReview = true;
        var submitButton = $(this);
        var originalHTML = submitButton.html();
        submitButton.prop('disabled', true);
        submitButton.empty().html('<i class="fa fa-spinner fa-spin"></i> Submitting...');

        var formData = {
            reviewer_name: $('#reviewerName').val(),
            rating: $('#reviewRating').val(),
            review_text: $('#reviewText').val(),
            partner_id: parseInt($('#reviewPartnerId').val(), 10),
            company_fax: $('#reviewForm [name="company_fax"]').val(),
        };

        console.log('Submitting review data:', formData);

        $.ajax({
            url: '/create_review',
            type: 'POST',
            contentType: 'application/json',
            dataType: 'json',
            data: JSON.stringify(formData),
            beforeSend: function() {
                console.log('Sending review request to server');
            },
            success: function(response) {
                console.log("Full review response:", response);
                console.log("Response type:", typeof response);
                
                // Handle both direct response and wrapped response formats
                var result = response.result || response;
                console.log("Result:", result);
                console.log("Status:", result.status);
                console.log("Message received:", result.message);

                if (result.status === 'success') {
                    // Show success message
                    $('#reviewSuccessMessage').text(result.message).show();
                    // Hide the form after successful submission
                    $('#reviewForm').hide();
                    
                    // Auto-close the modal after 1.5 seconds
                    setTimeout(function() {
                        $('#reviewModal').modal('hide');
                        // Reset the form and show it again for next use
                        $('#reviewForm').show();
                        $('#reviewSuccessMessage').hide();
                        $('#reviewForm')[0].reset();
                        // Reset stars to 5
                        $('#reviewRating').val('5');
                        $('.star').each(function() {
                            $(this).html('&#9734;');
                        });
                        $('.star').slice(0, 5).each(function() {
                            $(this).html('&#9733;');
                        });
                    }, 1500);
                } else {
                    $('#reviewSuccessMessage').removeClass('alert-success').addClass('alert-danger');
                    $('#reviewSuccessMessage').text(result.message || 'Unknown error occurred').show();
                }
            },
            error: function(xhr, status, error) {
                console.log('Error during review request:', error);
                console.log('Response text:', xhr.responseText);
                
                var errorMessage = 'An error occurred. Please try again.';
                try {
                    var response = JSON.parse(xhr.responseText);
                    if (response.message) {
                        errorMessage = response.message;
                    }
                } catch (e) {
                    // If response is not JSON, use default message
                }
                
                $('#reviewSuccessMessage').removeClass('alert-success').addClass('alert-danger');
                $('#reviewSuccessMessage').text(errorMessage).show();
            },
            complete: function() {
                console.log('Review AJAX request complete');
                submitButton.prop('disabled', false);
                submitButton.html(originalHTML);
                isSubmittingReview = false;
            }
        });
        
        return false; // Ensure form submission is completely prevented
    });
    
    // Handle service request button clicks - populate modal with service info
    $(document).on('click', '.service-request-btn', function() {
        var serviceId = $(this).data('service-id');
        var serviceName = $(this).data('service-name');
        var serviceDescription = $(this).data('service-description');
        
        // Populate hidden fields
        $('#serviceRequestServiceId').val(serviceId);
        $('#serviceRequestServiceName').val(serviceName);
        $('#serviceRequestServiceDescription').val(serviceDescription);
        
        // Display service info (title only, no description)
        $('#serviceRequestServiceDisplay').html('<strong>' + serviceName + '</strong>');

        // Load custom questions for this service
        loadServiceQuestions(serviceId);
    });
    
    // Reset service request form when modal is closed
    $('#serviceRequestModal').on('hidden.bs.modal', function() {
        $('#serviceRequestForm').show();
        $('#serviceRequestSuccessMessage').hide();
        $('#serviceRequestForm')[0].reset();
        $('#serviceRequestServiceDisplay').html('');
        $('#serviceRequestCustomQuestions').empty();
        isSubmittingServiceRequest = false;
    });

    function loadServiceQuestions(serviceId) {
        var $container = $('#serviceRequestCustomQuestions');
        $container.empty();

        if (!serviceId) {
            return;
        }

        $.ajax({
            url: '/service/questions',
            type: 'POST',
            contentType: 'application/json',
            dataType: 'json',
            data: JSON.stringify({ service_id: serviceId }),
            success: function(response) {
                var result = response.result || response;
                if (result.status === 'ok' && result.questions && result.questions.length) {
                    renderServiceQuestions(result.questions);
                }
            },
            error: function(xhr, status, error) {
                console.error('Error loading service questions:', status, error);
            }
        });
    }

    function renderServiceQuestions(questions) {
        var $container = $('#serviceRequestCustomQuestions');
        $container.empty();

        if (!questions || !questions.length) {
            return;
        }

        questions.forEach(function(q) {
            var requiredMark = q.is_required ? '<span class="text-danger">*</span>' : '';
            var requiredAttr = q.is_required ? ' required="required"' : '';
            var fieldId = 'serviceQuestion_' + q.id;
            var commonAttrs = ' data-question-id="' + q.id + '"' +
                              ' data-question-label="' + q.name + '"' +
                              ' data-question-type="' + q.field_type + '"';

            var html = '<div class="form-group">' +
                       '<label for="' + fieldId + '">' + q.name + requiredMark + '</label>';

            if (q.field_type === 'long_text') {
                html += '<textarea class="form-control service-question-input"' +
                        ' id="' + fieldId + '"' + commonAttrs + requiredAttr +
                        ' rows="3"></textarea>';
            } else if (q.field_type === 'number') {
                html += '<input type="number" class="form-control service-question-input"' +
                        ' id="' + fieldId + '"' + commonAttrs + requiredAttr + '/>';
            } else if (q.field_type === 'checkbox') {
                html += '<div class="form-check">' +
                        '<input type="checkbox" class="form-check-input service-question-input"' +
                        ' id="' + fieldId + '"' + commonAttrs + '/>' +
                        '<label class="form-check-label" for="' + fieldId + '">Yes</label>' +
                        '</div>';
            } else if (q.field_type === 'select') {
                html += '<select class="form-control service-question-input"' +
                        ' id="' + fieldId + '"' + commonAttrs + requiredAttr + '>';
                if (q.options) {
                    q.options.split(',').forEach(function(optRaw) {
                        var opt = optRaw.trim();
                        if (opt) {
                            html += '<option value="' + opt + '">' + opt + '</option>';
                        }
                    });
                }
                html += '</select>';
            } else {
                // default: short_text
                html += '<input type="text" class="form-control service-question-input"' +
                        ' id="' + fieldId + '"' + commonAttrs + requiredAttr + '/>';
            }

            html += '</div>';
            $container.append(html);
        });
    }
    
    // Service request form submission handler
    $(document).on('click', '#submitServiceRequestBtn', function(event) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        console.log('Submit service request button clicked');

        if (isSubmittingServiceRequest) {
            console.log('Service request submission already in progress, aborting');
            return false;
        }

        isSubmittingServiceRequest = true;
        var submitButton = $(this);
        var originalHTML = submitButton.html();
        submitButton.prop('disabled', true);
        submitButton.empty().html('<i class="fa fa-spinner fa-spin"></i> Sending...');

        // Get full phone number with country code from intl-tel-input
        var phoneNumber = '';
        try {
            if (typeof window.intlTelInput !== 'undefined' && $('#serviceRequestPhone').length) {
                var phoneInput = $('#serviceRequestPhone')[0];
                if (phoneInput && window.intlTelInputGlobals && window.intlTelInputGlobals.getInstance) {
                    var iti = window.intlTelInputGlobals.getInstance(phoneInput);
                    if (iti) {
                        phoneNumber = iti.getNumber();
                    }
                }
            }
            // Fallback to hidden field or direct input value
            if (!phoneNumber) {
                phoneNumber = $('#serviceRequestPhoneFull').val() || $('#serviceRequestPhone').val() || '';
            }
        } catch(e) {
            console.log('Error getting phone number:', e);
            phoneNumber = $('#serviceRequestPhoneFull').val() || $('#serviceRequestPhone').val() || '';
        }

        var formData = {
            contact_name: $('#serviceRequestFullName').val(),
            email_from: $('#serviceRequestEmail').val(),
            phone: phoneNumber,
            partner_id: parseInt($('#serviceRequestPartnerId').val(), 10),
            service_id: parseInt($('#serviceRequestServiceId').val(), 10),
            service_name: $('#serviceRequestServiceName').val(),
            service_description: $('#serviceRequestServiceDescription').val(),
            notes: $('#serviceRequestNotes').val(),
            company_fax: $('#serviceRequestForm [name="company_fax"]').val(),
        };
        
        console.log('Service Request - Submitting data:', formData);

        // Collect custom question answers
        var customAnswers = [];
        $('#serviceRequestCustomQuestions .service-question-input').each(function() {
            var $input = $(this);
            var id = parseInt($input.data('question-id'), 10);
            var label = $input.data('question-label') || '';
            var type = $input.data('question-type') || 'short_text';
            var value;

            if (type === 'checkbox') {
                value = $input.is(':checked');
            } else {
                value = $input.val();
            }

            customAnswers.push({
                id: id,
                label: label,
                type: type,
                value: value
            });
        });

        formData.custom_answers = customAnswers;

        console.log('Submitting service request data:', formData);

        $.ajax({
            url: '/create_service_request',
            type: 'POST',
            contentType: 'application/json',
            dataType: 'json',
            data: JSON.stringify(formData),
            beforeSend: function() {
                console.log('Sending service request to server');
            },
            success: function(response) {
                console.log("Full service request response:", response);
                
                var result = response.result || response;
                console.log("Result:", result);
                console.log("Status:", result.status);

                if (result.status === 'success') {
                    // Show success message
                    $('#serviceRequestSuccessMessage').text(result.message || 'Thank you! Your service request has been sent. We\'ll be in touch shortly.').show();
                    // Hide the form after successful submission
                    $('#serviceRequestForm').hide();
                    
                    // Auto-close the modal after 1.5 seconds
                    setTimeout(function() {
                        $('#serviceRequestModal').modal('hide');
                        // Reset the form and show it again for next use
                        $('#serviceRequestForm').show();
                        $('#serviceRequestSuccessMessage').hide();
                        $('#serviceRequestForm')[0].reset();
                        $('#serviceRequestServiceDisplay').html('');
                    }, 1500);
                } else {
                    $('#serviceRequestSuccessMessage').removeClass('alert-success').addClass('alert-danger');
                    $('#serviceRequestSuccessMessage').text(result.message || 'Unknown error occurred').show();
                }
            },
            error: function(xhr, status, error) {
                console.log('Error during service request:', error);
                console.log('Response text:', xhr.responseText);
                
                var errorMessage = 'An error occurred. Please try again.';
                try {
                    var response = JSON.parse(xhr.responseText);
                    if (response.message) {
                        errorMessage = response.message;
                    }
                } catch (e) {
                    // If response is not JSON, use default message
                }
                
                $('#serviceRequestSuccessMessage').removeClass('alert-success').addClass('alert-danger');
                $('#serviceRequestSuccessMessage').text(errorMessage).show();
            },
            complete: function() {
                console.log('Service request AJAX request complete');
                submitButton.prop('disabled', false);
                submitButton.html(originalHTML);
                isSubmittingServiceRequest = false;
            }
        });
        
        return false; // Ensure form submission is completely prevented
    });
});
