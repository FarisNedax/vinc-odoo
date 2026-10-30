# Vinc for Odoo - Digital Business Cards & Lead Capture Module

**Standalone Odoo Module - Single Purchase | Self-Hosted | Full Control**

**Vinc** brings digital business cards and lead capture directly into your Odoo database. This is the **standalone module version** for Odoo users who want complete self-hosted control with a one-time purchase.

> **💡 Prefer a hosted solution?** Check out [Vinc SaaS](https://getvinc.com) - our subscription-based hosted platform with the same features, zero setup required.

## 🎯 About This Version

This is the **standalone Odoo module** designed for:
- ✅ **Odoo owners** who already have their own Odoo instance
- ✅ **One-time purchase** - no recurring subscriptions
- ✅ **Complete self-hosting** - all data stays in your Odoo database
- ✅ **Full customization** - modify and extend as needed
- ✅ **No external dependencies** - everything runs in your environment

**Perfect for:** Companies with existing Odoo deployments who want Vinc's digital business card capabilities integrated directly into their system.

## 🌟 Overview

Vinc replaces paper business cards with intelligent, dynamic digital cards that:
- **Capture leads automatically** through built-in forms directly into Odoo CRM
- **Track every interaction** with detailed analytics
- **Integrate seamlessly** with Odoo's built-in CRM and email marketing
- **Collect reviews** and showcase social proof
- **Update in real-time** - changes reflect instantly for everyone
- **All data stored in your Odoo database** - no external data storage

**Core Value Proposition:** Digital business cards with built-in CRM integration, automatic lead collection, email marketing sync, and comprehensive analytics—all self-hosted in your Odoo instance with a single one-time purchase.

---

## ✨ Key Features

### 🎨 Five Professional Website Templates

Choose from five beautifully designed templates, each optimized for different use cases:

1. **Classic** - Traditional, clean layout with centered profile picture and gradient design
2. **Modern** - Contemporary design with inline action buttons and side-by-side layout
3. **Corporate** - Professional business-focused template with structured sections
4. **Minimal** - Clean, tabbed navigation for a compact, minimalistic experience
5. **Creative** - Playful design with floating background elements and maximum customization

All templates feature:
- Fully responsive design (mobile, tablet, desktop)
- Customizable primary and secondary colors
- Banner image support
- Social media integration (30+ platforms)
- Review carousels
- Service showcases
- Video embedding

### 📱 NFC & QR Code Technology

- **Dynamic QR Code Generation** - Unique QR codes for each card with custom patterns:
  - Square
  - Dots
  - Classy
  - Classy Rounded
  - Rounded
- **Logo Overlay** - Add company logo to center of QR code
- **NFC-Ready** - Universal onboarding URL (`/get-started`) for NFC cards/bands
- **Scan Tracking** - Analytics for every QR scan and NFC tap
- **Download QR Code** - Export high-resolution QR images

### 👥 Lead Generation & CRM Integration

- **Built-in Lead Forms** - Collect contact information from visitors
- **Automatic CRM Integration** - Leads automatically create opportunities in Odoo CRM
- **Lead Tagging** - Assign CRM tags to organize leads
- **Instant Lead-Back** - Automated follow-up emails and messaging:
  - Configurable email templates with placeholders
  - Automated WhatsApp/Viber/Telegram links
  - Customizable delay timing (immediate to days)
  - Pre-built template presets (friendly, professional, event mode)
- **Email Marketing Sync** - Leads automatically added to Odoo mailing lists
- **Lead Notifications** - Email alerts for new submissions

### ⭐ Review Management

- **Collect Reviews** - Visitors can submit reviews directly on the card
- **Display Social Proof** - Showcase reviews with ratings and testimonials
- **Review Carousel** - Automatic scrolling carousel with navigation
- **Review Moderation** - Publish/unpublish reviews
- **Rating System** - 1-5 star ratings
- **Custom Thank You Messages** - Personalized responses after review submission

### 🎯 Services Showcase

- **Service Listings** - Display services with descriptions
- **Service Pricing** - Show pricing information
- **Service Descriptions** - Rich HTML content for detailed service information
- **Request Service Button** - Generate leads for service inquiries
- **Service Modals** - Professional popups for service requests

### 🎬 Media & Content

- **Video Embedding** - Add YouTube videos to showcase work
- **Profile Photos** - Upload professional headshots
- **Banner Images** - Customizable header banners for each template
- **Rich About Sections** - HTML editor for detailed bios and company descriptions
- **External Website Links** - Add multiple websites with custom button labels

### 📊 Analytics & Tracking

- **Page View Count** - Track total visits to your card
- **QR Scan Count** - Monitor QR code usage
- **Lead Analytics** - Monthly lead counts and trends
- **Month-over-Month Comparison** - Track growth metrics

### 📧 Email Marketing Integration

- **Mailing Lists** - Create and manage email lists using Odoo's mass mailing
- **Automatic List Building** - Leads automatically added to lists
- **Mass Mailing Integration** - Full Odoo mass mailing functionality
- **Email Campaigns** - Send marketing emails to collected leads
- **Contact Management** - Comprehensive contact database

### 👥 Bulk Onboarding

- **CSV/Excel Upload** - Upload multiple users at once via spreadsheet
- **Batch Processing** - Process hundreds of users in the background
- **Magic Link Activation** - Secure token-based account activation
- **Automatic vCard Creation** - Pre-populated cards for each user
- **Progress Tracking** - Real-time batch status and completion reports
- **Email Invitations** - Automated welcome emails with activation links
- **Completion Notifications** - Summary emails with batch statistics
- **Resend Invitations** - Re-send activation links for failed users

### ✍️ Email Signature Generator

- **Professional Signatures** - Create HTML signatures for Gmail, Outlook, Apple Mail
- **5 Premium Templates** - Modern, Classic, Minimal, Corporate, Creative
- **Dynamic Content** - Auto-populates with your card details and photo
- **QR Code Integration** - Scannable QR code for instant connecting
- **One-Click Copy** - Instantly copy formatted HTML to clipboard
- **Fully Unlocked** - All templates available without plan restrictions

### 🎥 Virtual Meeting Backgrounds

- **Professional Backgrounds** - Custom 1920x1080 backgrounds for Zoom, Teams, or Meet
- **4 Layout Styles** - Classic, Modern, Minimal, Corporate
- **Smart Overlays** - Auto-adds your name, title, company, and QR code
- **Background Options** - Choose from:
  - 10 Professional Solid Colors
  - 6 Beautiful Gradients
  - 7 High-Quality Office/Abstract Images
  - **Custom Image Upload** - Use your own photo or office view
  - **Company Logo** - Overlay your brand logo

---

## 🚀 Quick Start

### Prerequisites

- **Odoo 19.0**
- **Python 3.10** or later
- **PostgreSQL** database
- Required Python packages (see `requirements.txt`)

### Installation

> **📝 Note:** This module requires an existing Odoo 19.0 installation. If you don't have Odoo yet, you can either install it yourself or consider our [SaaS version](https://vinculumapp.com) for instant access without setup.

1. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Copy module** to your Odoo addons directory:
   ```bash
   cp -r qr_code_odoo /path/to/odoo/addons/qr_code_odoo
   ```
   
   > **Important:** Make sure the module folder name matches exactly (`qr_code_odoo`)

3. **Restart Odoo server**:
   ```bash
   ./odoo-bin -c odoo.conf
   ```

4. **Update Apps List** in Odoo:
   - Go to Apps → Update Apps List
   - Make sure "Apps" filter is set to show all apps

5. **Install the Module**:
   - Search for "Vinc" in the Apps menu
   - Click Install
   - Follow the on-screen prompts

6. **Activate License** (if applicable):
   - After installation, you may need to activate your license key
   - Check Settings → Vinc License (if license validation is enabled)

### First-Time Setup

1. **Create Your First Card**:
   - Navigate to Vinc → Cards
   - Click "Create"
   - Fill in basic information:
     - Name, title, company
     - Phone, email, address
     - Profile photo and banner
     - Primary and secondary colors

2. **Choose Template**:
   - Select from Classic, Modern, Corporate, Minimal, or Creative
   - Each template has unique design characteristics

3. **Configure Settings**:
   - Set website slug (URL identifier)
   - Enable lead collection if desired
   - Add social media links
   - Configure reviews section

4. **Generate Website**:
   - Click "Generate Website" button
   - Your card is now live at: `https://yourdomain.com/{slug}`

5. **Download QR Code**:
   - Use the QR code download button
   - Print or share the QR code

---

## 🔐 Permissions & Access Control

Vinc ships with a two-tier permission model enforced at the Odoo ORM layer
via `ir.rule` records — no application-level sprinkling, no trust on client
code.

| Role | Who | Sees / can modify |
| --- | --- | --- |
| **Regular internal user** (`base.group_user`) | Every user you create in Odoo | Only the vCards, leads, reviews, downloads, follow-up reminders and leadback settings that **they themselves created**. Cannot read / write / unlink another user's records, and has **no access** to the bulk onboarding models. |
| **Vinc Manager** (`qr_code_odoo.group_vinc_manager`) | Granted manually from Settings → Users & Companies → Users → *Vinc* tab | Sees and manages **every** vCard, lead, review, tracking row and bulk-onboarding batch on the instance. Required for the `/bulk-onboard` flow. |
| **Odoo administrator** (`base.group_system`) | Odoo's built-in Administration group | Implicitly gets Vinc Manager via `implied_ids` — no extra step. |

### Granting the Vinc Manager role

1. Go to **Settings → Users & Companies → Users** and pick a user.
2. Switch to the **Access Rights** tab.
3. Under the **Vinc** category, set the access level to **Vinc Manager**.
4. Save.

The user can now see all cards on the instance and run bulk-onboarding campaigns.

### What's locked down

- `bulk.onboarding.batch`, `bulk.onboarding.rep`, and `bulk.onboarding.token` are
  **Vinc-Manager-only** at the ACL level. Regular users cannot enumerate magic-link
  tokens even via direct RPC. The activation controller itself uses `sudo()` to
  look up tokens by value, so the flow still works for recipients.
- `partner.vcard` and all its children (`.website`, `.videos`, `.reviews`,
  `.speciality`, `.service`, `.service.question`) are scoped to the creator's
  `create_uid` for non-managers.
- `vcard.download.tracking`, `followup.reminder`, `followup.scheduled.reminder`,
  `leadback.*` and `user.dashboard` all get the same per-owner isolation.
- Service descriptions, review text and the free-form About field are stored as
  sanitised HTML (`sanitize=True, sanitize_tags=True, sanitize_attributes=True`).
  Published-card templates render these fields with `t-esc` as defense-in-depth.

### Required Odoo / server configuration

A few instance-level settings must be correct for Vinc to work well in production:

- **`web.base.url`** — *Settings → Technical → System Parameters*. The
  full `https://yourdomain.com` (no trailing slash). Vinc uses this for
  QR-code URLs, vCard download links, intro / notification / digest email
  bodies, and magic-link activations. If this is wrong or blank, customers
  receive emails and QR codes pointing at the wrong host.
- **Outgoing mail server** — *Settings → Technical → Outgoing Mail Servers*.
  Required for lead-notification emails, intro emails, digest emails,
  leadback emails, and bulk-onboarding magic links. Without a working SMTP
  relay the "Mail: Send Email Queue" cron silently fails.
- **Website host** — the module binds its routes under the default website.
  If you run multi-website, pick which website hosts the `/get-started`,
  `/vinculum/guide`, `/nfc/setup/<id>`, and `/bulk-onboard` routes.

### Optional modules that change behaviour

- **`auth_signup`** — if installed, anyone can self-register via `/web/signup`.
  New signups get a plain `base.group_user` with zero access to existing
  cards / leads (thanks to the record rules above). They can only create
  their own card from `/get-started`. Grant Vinc Manager manually if you
  want that user to see everything.
- **`crm`** is a hard dependency — leads captured through the public lead
  form land in the CRM pipeline of the card owner.

### Public vs. authenticated routes

| Route | Auth | Purpose |
| --- | --- | --- |
| `/<slug>` | public | Published vCard page |
| `/create_lead` | public (JSON, csrf=False) | Lead form submission from a published card |
| `/create_review` | public | Review submission |
| `/create_service_request` | public | Service request submission |
| `/vcard/qr_code/download/<id>` | public | QR code image download |
| `/website/vcard/download/<id>` | public | `.vcf` download |
| `/get-started` | user | Card creation wizard (5-chapter editorial flow) |
| `/vcard/submit` | user | POST target of `/get-started` |
| `/vcard/preview` | user (JSON-RPC) | Live preview used by the `/get-started` iframe |
| `/nfc/setup/<partner_id>` | public | NFC programming walkthrough, linked from the card form |
| `/vinculum/guide` | public | In-product user + admin guide (8 topics) |
| `/bulk-onboard` | manager | CSV / Excel bulk card creation + magic-link activation |
| `/bulk-onboard/activate/<token>` | public | Magic-link activation for invited users |

---

## 📖 User Guide

### Creating a Card

1. **Basic Information**
   - Name, Job Position, Company Name
   - Primary Phone, Mobile Phone, Email
   - Address (Street, City, State, ZIP, Country)

2. **Visual Customization**
   - Upload profile photo (recommended: 125x125px or larger)
   - Upload banner image (recommended: 1200x400px)
   - Choose primary color (background color)
   - Choose secondary color (buttons, accents)

3. **Content Sections**
   - **About** - Rich HTML editor for bio/description
   - **Specialties** - Add specialty tags/keywords
   - **Services** - List services with pricing and descriptions
   - **Videos** - Add YouTube video URLs
   - **Websites** - Add external links with custom labels
   - **Reviews** - Configure review display settings

4. **Social Media** (30+ platforms supported)
   - LinkedIn, Facebook, Instagram, Twitter
   - WhatsApp, Viber, Telegram
   - YouTube, TikTok, Snapchat
   - And many more...

5. **Lead Collection Setup**
   - Enable "Show the lead collection form"
   - Set button label (e.g., "Drop Your Info", "Get in Touch")
   - Configure thank you message
   - Assign lead tags for CRM organization
   - Select email marketing list

6. **Instant Lead-Back Configuration** (Optional)
   - Enable automated follow-up emails
   - Choose email template preset or create custom
   - Configure delay timing
   - Enable click-to-chat messaging links
   - Set up message templates

### Template-Specific Features

#### Classic Template
- Centered profile picture with shadow
- Gradient header with banner
- Bootstrap carousel for reviews
- Service cards with pricing
- Multiple action buttons (Call, Email, Drop Info, Download Info)

#### Modern Template
- Side-by-side layout
- Inline action buttons in header
- Horizontal review carousel with navigation arrows
- Contact information grid
- Social media icons section

#### Corporate Template
- Professional banner header
- Structured sections layout
- Contact information panel
- Services and specialties sections
- Professional button styling

#### Minimal Template
- Tabbed navigation (Contact, Services, Reviews, Websites, QR Code, Calendar)
- Vertical review list (no carousel)
- Compact design with maximum white space
- Calendar integration (Calendly)
- Minimalist aesthetic

#### Creative Template
- Floating background elements in secondary color
- QR code share icon over profile picture
- Maximum rounded buttons (pill shape)
- Subtle animations on interactive elements
- Integrated contact info in About section

### Lead Management

1. **View Leads**:
   - Click "Leads" smart button on card record
   - Or navigate to CRM → Leads
   - Filter by card or assignee

2. **Lead Information**:
   - Contact name, phone, email
   - Company, job title
   - Submission timestamp
   - Associated tags

3. **Follow-Up**:
   - Convert leads to opportunities
   - Assign to sales team
   - Add notes and activities
   - Track through sales pipeline

### Review Management

1. **Configure Reviews**:
   - Enable "Show Reviews Section"
   - Set section title
   - Configure max reviews to display
   - Set carousel autoscroll speed
   - Customize thank you message

2. **Add Reviews**:
   - Go to Reviews tab in card form
   - Click "Add a line" in Reviews list
   - Enter reviewer name, rating (1-5 stars), review text
   - Set sequence for display order
   - Publish/unpublish reviews

3. **Public Review Submission**:
   - Visitors can submit reviews via card website
   - Reviews appear after moderation
   - Automatic thank you message displayed

### ✍️ Email Signatures

1. **Access**: Go to the **Email Signatures** tab on your card record.
2. **Select Template**: Choose from 5 professional designs.
3. **Preview**: See a live preview with your actual data.
4. **Copy**: Click "Copy Signature" to copy the HTML code.
5. **Paste**: Paste into your email client's signature settings (Gmail, Outlook, etc.).

### 🎥 Virtual Backgrounds

1. **Access**: Go to the **Virtual Backgrounds** tab.
2. **Customize**:
   - **Layout**: Choose how your info is displayed.
   - **Background**: Pick a color, gradient, or upload your own image.
   - **Logo**: Optionally upload your company logo to overlay.
3. **Download**: Click "Download Background" to save a 1920x1080 PNG.
4. **Use**: Upload to Zoom/Teams as a custom virtual background.

---

## 🏗️ Technical Architecture

### Models

#### Core Models
- **`partner.vcard`** - Main card model with all configuration
- **`partner.vcard.website`** - External website links
- **`partner.vcard.videos`** - Video content
- **`partner.vcard.reviews`** - Review management
- **`partner.vcard.services`** - Service listings
- **`crm.lead`** - Lead/opportunity records (inherited from Odoo CRM)

#### Supporting Models
- **`mailing.list`** - Email marketing lists (Odoo mass_mailing)
- **`leadback.scheduled.email`** - Scheduled email automation
- **`leadback.messaging.channel`** - Messaging platform configuration
- **`bulk.onboarding.batch`** - Bulk onboarding batch records
- **`bulk.onboarding.rep`** - Individual user records in a batch
- **`bulk.onboarding.token`** - Magic link activation tokens

### Controllers

- **`/qr_code/<slug>`** - Public card website route
- **`/get-started`** - Onboarding form for new users
- **`/bulk-onboard`** - Bulk onboarding dashboard
- **`/bulk-onboard/new`** - Create new bulk onboarding batch
- **`/bulk-onboard/batch/<id>`** - View batch details and progress
- **`/bulk-onboard/activate`** - Magic link activation page
- **`/api/lead`** - Lead form submission API
- **`/api/review`** - Review submission API
- **`/api/service-request`** - Service request API

### Views

#### Backend Views
- **Card Form View** - Comprehensive card configuration
- **Lead List/Form** - CRM integration views
- **Review Management** - Review CRUD operations

#### Frontend Templates (QWeb)
- **Classic Template** - `_build_classic_template()`
- **Modern Template** - `_build_modern_template()`
- **Corporate Template** - `_build_corporate_template()`
- **Minimal Template** - `_build_minimal_template()`
- **Creative Template** - `_build_creative_template()`

### JavaScript

- **`widget.js`** - Frontend functionality:
  - Lead form submission
  - Review submission
  - Service request forms
  - Modal interactions
  - Carousel controls
  - Phone input internationalization
- **`signature_generator.js`** - Email signature generation logic
- **`virtual_bg_generator.js`** - Virtual background canvas generation

### Assets

- **CSS**:
  - `reviews_backend.css` - Review management styling
  - `mobile_tables.css` - Mobile responsive tables

---

## 🔧 Configuration

### Website Configuration

- **Website Slug** - URL identifier (e.g., `john-doe` → `yourdomain.com/john-doe`)
- **Primary Color** - Background color for all templates
- **Secondary Color** - Accent color for buttons, sections, highlights
- **Website Template** - Choose from 5 available templates

### QR Code Settings

- **QR Pattern** - Visual style (Square, Dots, Classy, etc.)
- **QR Logo** - Optional logo overlay in center
- **Download QR Code** - Export high-resolution image

### Lead Collection Settings

- **Show Lead Form** - Enable/disable form display
- **Button Label** - Customize call-to-action text
- **Thank You Message** - Post-submission message
- **Lead Tags** - CRM organization tags
- **Email Marketing List** - Automatic list assignment
- **Notify on New Lead** - Email alerts

### Instant Lead-Back Settings

- **Enable Instant Lead-Back** - Master toggle
- **Automated Email**:
  - Template presets (Friendly, Professional, Event Mode, etc.)
  - Custom HTML templates with placeholders
  - Delay timing (immediate to days)
- **Click to Chat**:
  - Messaging platforms (WhatsApp, Viber, Telegram)
  - Message templates with placeholders
  - Delay timing

### Review Settings

- **Show Reviews Section** - Enable/disable
- **Section Title** - Custom heading
- **Max Reviews to Display** - Limit shown reviews
- **Carousel Autoscroll Speed** - Auto-rotation timing
- **Thank You Message** - Post-submission message

---

## 📱 NFC Integration

### Universal Onboarding URL

All NFC cards/bands should be programmed with:
- **Primary URL**: `https://yourdomain.com/get-started`

This universal URL works for all users:
- New users → Onboarding flow
- Existing users → Direct to their card

### NFC Card Programming

Program NFC cards/bands with:
- **URL**: `https://yourdomain.com/get-started`
- **NDEF Format**: URI Record
- **Action**: Open URL

---

## 🔌 Integrations

### CRM Integration (Odoo)

- **Automatic Lead Creation** - Form submissions create CRM leads
- **Lead Tagging** - Automatic tag assignment
- **Opportunity Pipeline** - Convert leads to opportunities
- **Activity Tracking** - Log all interactions

### Email Marketing (Odoo Mass Mailing)

- **Automatic List Building** - Leads added to mailing lists
- **Campaign Management** - Send marketing emails
- **Contact Segmentation** - Tag-based lists
- **Analytics** - Open rates, click rates, conversions

### Social Media (30+ Platforms)

Supported platforms include:
- **Professional**: LinkedIn, Xing
- **Social**: Facebook, Instagram, Twitter, TikTok
- **Messaging**: WhatsApp, Viber, Telegram, Signal, Line
- **Video**: YouTube, Vimeo, TikTok
- **Business**: Google Reviews, Yelp, TripAdvisor
- **Delivery**: DoorDash, Uber Eats
- **And many more...**

### Calendar Integration

- **Calendly** - Booking link integration (Minimal template)
- **Calendar URL** - Custom calendar URL support

---

## 📊 API Reference

### Submit Lead

**Endpoint**: `/api/lead`  
**Method**: POST  
**Content-Type**: `application/x-www-form-urlencoded`

**Parameters**:
- `vcard_id` (required) - Card ID
- `contact_name` (required) - Contact full name
- `contact_email` (required) - Email address
- `contact_phone` (optional) - Phone number
- `contact_company` (optional) - Company name
- `contact_title` (optional) - Job title

**Response**:
```json
{
  "success": true,
  "message": "Thank you for your submission!"
}
```

### Submit Review

**Endpoint**: `/api/review`  
**Method**: POST  
**Content-Type**: `application/x-www-form-urlencoded`

**Parameters**:
- `vcard_id` (required) - Card ID
- `reviewer_name` (required) - Reviewer name
- `rating` (required) - Rating 1-5
- `review_text` (required) - Review content

**Response**:
```json
{
  "success": true,
  "message": "Thank you for your review!"
}
```

### Submit Service Request

**Endpoint**: `/api/service-request`  
**Method**: POST  
**Content-Type**: `application/x-www-form-urlencoded`

**Parameters**:
- `vcard_id` (required) - Card ID
- `service_id` (required) - Service ID
- `contact_name` (required) - Contact name
- `contact_email` (required) - Email
- `contact_phone` (optional) - Phone
- `message` (optional) - Additional message

**Response**:
```json
{
  "success": true,
  "message": "Request submitted successfully!"
}
```

---

## 🐛 Troubleshooting

### Common Issues

#### Module Won't Install
- **Solution**: Ensure Odoo 19.0 is installed
- **Check**: Python version (3.10+ required)
- **Verify**: All dependencies installed (`pip install -r requirements.txt`)

#### QR Code Not Generating
- **Solution**: Check if Pillow is properly installed
- **Verify**: Image upload permissions
- **Check**: Server logs for errors

#### Website Not Accessible
- **Solution**: Ensure website slug is set
- **Verify**: "Generate Website" button was clicked
- **Check**: Website page is published
- **Verify**: Domain configuration in Odoo

#### Lead Forms Not Working
- **Solution**: Check if "Show the lead collection form" is enabled
- **Verify**: CRM module is installed
- **Check**: JavaScript console for errors
- **Verify**: Email marketing list is assigned

#### Template Not Applying
- **Solution**: Ensure "Generate Website" is clicked after template change
- **Check**: Template name matches Selection option exactly
- **Verify**: No parsing errors in server logs

#### Modals Not Clickable
- **Solution**: Check z-index CSS conflicts
- **Verify**: Bootstrap modal JavaScript is loaded
- **Check**: No JavaScript errors in console

### Debug Mode

Enable debug mode in Odoo:
1. Go to Settings → Technical → Users → Users
2. Edit your user and enable "Technical Features"
3. Check server logs for detailed error information

---

## 📄 License

This module is licensed under **OPL-1** (Odoo Proprietary License v1.0).

**Copyright (C) 2024 Faris Delija. All Rights Reserved.**

See [LICENSE.txt](LICENSE.txt) for full license terms and restrictions.

---

## 💰 Pricing & Licensing

This is a **standalone Odoo module** available for **one-time purchase** on the Odoo App Store.

- ✅ **Single purchase** - Own it forever
- ✅ **No recurring fees** - No monthly or annual subscriptions
- ✅ **Self-hosted** - Full control over your data
- ✅ **Updates included** - Future module updates included in your purchase

> **Looking for a subscription-based option?** Check out [Vinc SaaS](https://getvinc.com) for a hosted solution with monthly/annual plans.

## 🤝 Support

For technical support on this module:
- **Email**: support@getvinc.com
- **Subject**: Include "[Odoo Module]" in your subject line
- Check the Odoo community forums
- Review the module documentation

**Support includes:**
- Installation assistance
- Bug fixes
- Module updates
- Technical documentation

> **Need professional setup help?** We offer paid implementation services - contact us for details.

---

## 🙏 Acknowledgments

Built with:
- **Odoo 19** - Enterprise resource planning platform
- **Bootstrap 4** - Frontend framework
- **QRCode** - QR code generation library
- **Pillow** - Image processing library
- **Intl Tel Input** - Phone number internationalization

---

**Vinc** - Transform every networking interaction into a measurable business opportunity.
