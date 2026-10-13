"""MCP server exposing the addy.io API as tools."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Sequence
from typing import Annotated, Any, Literal, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from addy_mcp import __version__
from addy_mcp.client import AddyClient

INSTRUCTIONS = """\
Tools for managing an addy.io (formerly AnonAddy) email-forwarding account.

Concepts:
- Alias: a forwarding address (e.g. shop123@anonaddy.me). Mail sent to it is forwarded to one or more recipients.
- Recipient: a real mailbox that aliases forward to. New recipients must be verified by email.
- Username: an extra username giving its own subdomain (e.g. anything@myname.anonaddy.com).
- Domain: a custom domain the user owns and has connected to addy.io.
- Rule: conditions + actions applied to forwarded/replied/sent mail.
- Blocklist: senders/domains whose mail is rejected.

Most tools take ids (UUIDs). Look them up with the list_* tools first.
Deleting an alias is reversible (restore_alias); forgetting an alias is permanent.
Confirm with the user before deleting or forgetting anything.
"""

READ_ONLY_ENV = "ADDY_READ_ONLY"

mcp = MCPServer("addy.io", instructions=INSTRUCTIONS)
api = AddyClient()

READ = ToolAnnotations(read_only_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
IDEMPOTENT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)

_F = TypeVar("_F", bound=Callable[..., Any])
WRITE_TOOLS: list[str] = []


def tool(annotations: ToolAnnotations) -> Callable[[_F], _F]:
    """Register a tool, remembering which ones can change the account (for read-only mode)."""

    def decorator(fn: _F) -> _F:
        if not annotations.read_only_hint:
            WRITE_TOOLS.append(fn.__name__)
        return mcp.tool(annotations=annotations)(fn)

    return decorator


Id = Annotated[str, Field(description="The id (UUID) of the item")]
IdList = list[str]
Page = Annotated[int | None, Field(description="Page number (1-based)", ge=1)]
PageSize = Annotated[int | None, Field(description="Results per page (1-100)", ge=1, le=100)]


def _bool(value: bool | None) -> str | None:
    return None if value is None else str(value).lower()


def _body(**fields: Any) -> dict[str, Any]:
    """Build a JSON body, dropping fields that weren't provided."""
    return {k: v for k, v in fields.items() if v is not None}


async def _toggle(resource: str, item_id: str, enabled: bool) -> Any:
    """addy.io turns options on with POST /{resource} {id} and off with DELETE /{resource}/{id}."""
    if enabled:
        return await api.request("POST", f"/{resource}", json={"id": item_id})
    return await api.request("DELETE", f"/{resource}/{item_id}")


# --------------------------------------------------------------------------- account


@tool(READ)
async def get_account_details() -> Any:
    """Get account details: username, plan/subscription, bandwidth used, default alias domain/format, limits, etc."""
    return await api.request("GET", "/account-details")


@tool(READ)
async def get_api_token_details() -> Any:
    """Get the name, creation date and expiry of the API token this server is using."""
    return await api.request("GET", "/api-token-details")


@tool(READ)
async def get_account_notifications() -> Any:
    """Get account notifications/announcements from addy.io."""
    return await api.request("GET", "/account-notifications")


@tool(READ)
async def get_domain_options() -> Any:
    """Get the domains available for creating aliases, plus the account's default alias domain and format."""
    return await api.request("GET", "/domain-options")


@tool(READ)
async def get_app_version() -> Any:
    """Get the addy.io app version (only available on self-hosted instances)."""
    return await api.request("GET", "/app-version")


# --------------------------------------------------------------------------- aliases

AliasSort = Literal[
    "local_part", "domain", "email", "emails_forwarded", "emails_blocked", "emails_replied", "emails_sent",
    "last_forwarded", "last_blocked", "last_replied", "last_sent", "last_used", "active", "created_at",
    "updated_at", "deleted_at",
]  # fmt: skip


@tool(READ)
async def list_aliases(
    search: Annotated[str | None, Field(description="Search alias email addresses and descriptions")] = None,
    active: Annotated[bool | None, Field(description="Only active (true) or inactive (false) aliases")] = None,
    deleted: Annotated[
        Literal["with", "only"] | None,
        Field(description="'with' to include deleted aliases, 'only' for just deleted ones. Default excludes them."),
    ] = None,
    pinned: Annotated[bool | None, Field(description="Only pinned (true) or unpinned (false) aliases")] = None,
    label_id: Annotated[str | None, Field(description="Only aliases with this label id")] = None,
    recipient_id: Annotated[str | None, Field(description="Only aliases forwarding to this recipient id")] = None,
    domain_id: Annotated[str | None, Field(description="Only aliases on this custom domain id")] = None,
    username_id: Annotated[str | None, Field(description="Only aliases on this username id")] = None,
    sort: Annotated[AliasSort | None, Field(description="Field to sort by")] = None,
    descending: Annotated[bool, Field(description="Sort descending")] = False,
    include: Annotated[
        Literal["recipients", "labels"] | None,
        Field(description="Also return each alias's recipients or labels (the API allows only one per request)"),
    ] = None,
    page: Page = None,
    page_size: PageSize = 25,
) -> Any:
    """List or search aliases. Results are paginated; the response includes `meta` with totals and page counts."""
    params = {
        "filter[search]": search,
        "filter[active]": _bool(active),
        "filter[deleted]": deleted,
        "filter[pinned]": _bool(pinned),
        "filter[label]": label_id,
        "recipient": recipient_id,
        "domain": domain_id,
        "username": username_id,
        "sort": f"-{sort}" if sort and descending else sort,
        "with": include,
        "page[number]": page,
        "page[size]": page_size,
    }
    return await api.request("GET", "/aliases", params=params)


@tool(READ)
async def get_alias(alias_id: Id) -> Any:
    """Get a single alias, including its recipients, labels and statistics."""
    return await api.request("GET", f"/aliases/{alias_id}")


@tool(WRITE)
async def create_alias(
    domain: Annotated[
        str, Field(description="Domain for the alias, e.g. 'anonaddy.me' or a custom domain/username domain")
    ],
    description: Annotated[str | None, Field(description="What the alias is for, e.g. 'Amazon'")] = None,
    format: Annotated[
        Literal[
            "random_characters",
            "uuid",
            "random_words",
            "random_male_name",
            "random_female_name",
            "random_noun",
            "custom",
        ]
        | None,
        Field(description="Alias format. 'custom' requires local_part and a custom domain or username domain."),
    ] = None,  # fmt: skip
    local_part: Annotated[str | None, Field(description="The part before the @ (only with format='custom')")] = None,
    recipient_ids: Annotated[
        IdList | None, Field(description="Recipients to forward to (default recipient if omitted)")
    ] = None,
    label_ids: Annotated[IdList | None, Field(description="Labels to attach")] = None,
) -> Any:
    """Create a new alias. Use get_domain_options to see which domains are available."""
    body = _body(
        domain=domain,
        description=description,
        format=format,
        local_part=local_part,
        recipient_ids=recipient_ids,
        label_ids=label_ids,
    )
    return await api.request("POST", "/aliases", json=body)


@tool(IDEMPOTENT)
async def update_alias(
    alias_id: Id,
    description: Annotated[str | None, Field(description="New description")] = None,
    from_name: Annotated[
        str | None, Field(description="Display name used when replying/sending from the alias")
    ] = None,
    label_ids: Annotated[IdList | None, Field(description="Replace the alias's labels with these")] = None,
) -> Any:
    """Update an alias's description, from name, or labels. Only the fields you pass are changed."""
    body = _body(description=description, from_name=from_name, label_ids=label_ids)
    if not body:
        raise ToolError("Provide at least one of description, from_name or label_ids.")
    return await api.request("PATCH", f"/aliases/{alias_id}", json=body)


@tool(DESTRUCTIVE)
async def delete_alias(alias_id: Id) -> Any:
    """Delete an alias. It stops receiving mail but can be brought back with restore_alias."""
    return await api.request("DELETE", f"/aliases/{alias_id}")


@tool(WRITE)
async def restore_alias(alias_id: Id) -> Any:
    """Restore a deleted alias."""
    return await api.request("PATCH", f"/aliases/{alias_id}/restore")


@tool(DESTRUCTIVE)
async def forget_alias(alias_id: Id) -> Any:
    """PERMANENTLY forget an alias: it is disassociated from the account and cannot be restored."""
    return await api.request("DELETE", f"/aliases/{alias_id}/forget")


@tool(IDEMPOTENT)
async def set_alias_option(
    alias_id: Id,
    option: Annotated[
        Literal["active", "pinned", "attached_recipients_only"],
        Field(
            description=(
                "'active': whether the alias forwards mail (inactive aliases silently discard it). "
                "'pinned': show first in lists. "
                "'attached_recipients_only': only recipients attached to this alias may reply/send from it."
            )
        ),
    ],
    enabled: bool,
) -> Any:
    """Turn an alias option on or off (activate/deactivate, pin/unpin, limit reply/send to attached recipients)."""
    resource = {
        "active": "active-aliases",
        "pinned": "pinned-aliases",
        "attached_recipients_only": "attached-recipients-only",
    }[option]
    return await _toggle(resource, alias_id, enabled)


@tool(IDEMPOTENT)
async def set_alias_recipients(
    alias_id: Id,
    recipient_ids: Annotated[
        IdList, Field(description="Recipients the alias should forward to (empty list = default recipient)")
    ],
    family_member_ids: Annotated[
        IdList | None, Field(description="Duo/Family plan member user ids to also deliver to")
    ] = None,
    family_reply_send_ids: Annotated[
        IdList | None, Field(description="Subset of family_member_ids allowed to reply/send from the alias")
    ] = None,
) -> Any:
    """Replace the set of recipients an alias forwards to."""
    body = _body(
        alias_id=alias_id,
        recipient_ids=recipient_ids,
        family_member_ids=family_member_ids,
        family_reply_send_ids=family_reply_send_ids,
    )
    return await api.request("POST", "/alias-recipients", json=body)


@tool(IDEMPOTENT)
async def set_alias_labels(
    alias_id: Id,
    label_ids: Annotated[IdList, Field(description="Labels the alias should have (empty list removes all)")],
) -> Any:
    """Replace the labels attached to an alias."""
    return await api.request("POST", "/alias-labels", json={"alias_id": alias_id, "label_ids": label_ids})


# --------------------------------------------------------------------------- alias bulk actions

BulkIds = Annotated[IdList, Field(description="Alias ids (max 25)", min_length=1, max_length=25)]


@tool(DESTRUCTIVE)
async def bulk_alias_action(
    action: Annotated[
        Literal["get", "activate", "deactivate", "pin", "unpin", "delete", "restore", "forget"],
        Field(description="What to do to every alias. 'forget' is permanent."),
    ],
    alias_ids: BulkIds,
) -> Any:
    """Apply one action to up to 25 aliases at once (or fetch them with action='get')."""
    return await api.request("POST", f"/aliases/{action}/bulk", json={"ids": alias_ids})


@tool(IDEMPOTENT)
async def bulk_set_alias_recipients(
    alias_ids: BulkIds,
    recipient_ids: Annotated[IdList, Field(description="Recipients every alias should forward to")],
    family_member_ids: Annotated[
        IdList | None, Field(description="Duo/Family plan member user ids to also deliver to")
    ] = None,
    family_reply_send_ids: Annotated[
        IdList | None, Field(description="Subset of family_member_ids allowed to reply/send")
    ] = None,
) -> Any:
    """Replace the recipients of up to 25 aliases at once."""
    body = _body(
        ids=alias_ids,
        recipient_ids=recipient_ids,
        family_member_ids=family_member_ids,
        family_reply_send_ids=family_reply_send_ids,
    )
    return await api.request("POST", "/aliases/recipients/bulk", json=body)


@tool(IDEMPOTENT)
async def bulk_set_alias_labels(
    alias_ids: BulkIds,
    label_ids: Annotated[IdList, Field(description="Labels every alias should have")],
) -> Any:
    """Replace the labels of up to 25 aliases at once."""
    return await api.request("POST", "/aliases/labels/bulk", json={"ids": alias_ids, "label_ids": label_ids})


# --------------------------------------------------------------------------- recipients


@tool(READ)
async def list_recipients(
    verified: Annotated[bool | None, Field(description="Only verified (true) or unverified (false)")] = None,
    include_alias_count: Annotated[bool, Field(description="Include how many aliases use each recipient")] = True,
) -> Any:
    """List the account's recipients (the real mailboxes aliases forward to)."""
    params = {"filter[verified]": _bool(verified), "filter[alias_count]": _bool(include_alias_count)}
    return await api.request("GET", "/recipients", params=params)


@tool(READ)
async def get_recipient(
    recipient_id: Id,
    include_alias_count: Annotated[bool, Field(description="Include how many aliases use this recipient")] = True,
) -> Any:
    """Get a single recipient and its settings."""
    params = {"filter[alias_count]": _bool(include_alias_count)}
    return await api.request("GET", f"/recipients/{recipient_id}", params=params)


@tool(WRITE)
async def create_recipient(email: Annotated[str, Field(description="The real email address to forward to")]) -> Any:
    """Add a new recipient. addy.io emails it a verification link; it can't be used until verified."""
    return await api.request("POST", "/recipients", json={"email": email})


@tool(IDEMPOTENT)
async def update_recipient(recipient_id: Id, description: str) -> Any:
    """Set a recipient's description."""
    return await api.request("PATCH", f"/recipients/{recipient_id}", json={"description": description})


@tool(DESTRUCTIVE)
async def delete_recipient(recipient_id: Id) -> Any:
    """Delete a recipient. Aliases that used it fall back to the default recipient."""
    return await api.request("DELETE", f"/recipients/{recipient_id}")


@tool(WRITE)
async def resend_recipient_verification(recipient_id: Id) -> Any:
    """Resend the verification email for an unverified recipient."""
    return await api.request("POST", "/recipients/email/resend", json={"recipient_id": recipient_id})


@tool(IDEMPOTENT)
async def add_recipient_public_key(
    recipient_id: Id,
    key_data: Annotated[str, Field(description="ASCII-armored public GPG/OpenPGP key")],
) -> Any:
    """Add a public GPG key to a recipient so forwarded mail can be encrypted."""
    return await api.request("PATCH", f"/recipient-keys/{recipient_id}", json={"key_data": key_data})


@tool(DESTRUCTIVE)
async def remove_recipient_public_key(recipient_id: Id) -> Any:
    """Remove a recipient's public GPG key (this also turns off encryption for it)."""
    return await api.request("DELETE", f"/recipient-keys/{recipient_id}")


@tool(IDEMPOTENT)
async def set_recipient_option(
    recipient_id: Id,
    option: Annotated[
        Literal[
            "active",
            "can_reply_send",
            "encryption",
            "inline_encryption",
            "protected_headers",
            "remove_pgp_keys",
            "remove_pgp_signatures",
        ],
        Field(
            description=(
                "'active': whether mail is forwarded to it. "
                "'can_reply_send': whether it may reply/send from aliases. "
                "'encryption': encrypt forwarded mail with its GPG key. "
                "'inline_encryption': use PGP/Inline instead of PGP/MIME. "
                "'protected_headers': hide the subject when encrypting. "
                "'remove_pgp_keys' / 'remove_pgp_signatures': strip these from forwarded mail."
            )
        ),
    ],
    enabled: bool,
) -> Any:
    """Turn a recipient option on or off."""
    resource = {
        "active": "active-recipients",
        "can_reply_send": "allowed-recipients",
        "encryption": "encrypted-recipients",
        "inline_encryption": "inline-encrypted-recipients",
        "protected_headers": "protected-headers-recipients",
        "remove_pgp_keys": "remove-pgp-keys-recipients",
        "remove_pgp_signatures": "remove-pgp-signatures-recipients",
    }[option]
    return await _toggle(resource, recipient_id, enabled)


# --------------------------------------------------------------------------- usernames


@tool(READ)
async def list_usernames() -> Any:
    """List the account's usernames (each gives a subdomain like name.anonaddy.com for on-the-fly aliases)."""
    return await api.request("GET", "/usernames")


@tool(READ)
async def get_username(username_id: Id) -> Any:
    """Get a single username and its settings."""
    return await api.request("GET", f"/usernames/{username_id}")


@tool(WRITE)
async def create_username(username: str) -> Any:
    """Create an additional username (counts against the plan's username limit)."""
    return await api.request("POST", "/usernames", json={"username": username})


@tool(IDEMPOTENT)
async def update_username(
    username_id: Id,
    description: str | None = None,
    from_name: Annotated[str | None, Field(description="Display name for replies/sends")] = None,
    auto_create_regex: Annotated[
        str | None, Field(description="Regex limiting which on-the-fly aliases may be auto-created")
    ] = None,
) -> Any:
    """Update a username's description, from name, or auto-create regex."""
    body = _body(description=description, from_name=from_name, auto_create_regex=auto_create_regex)
    if not body:
        raise ToolError("Provide at least one of description, from_name or auto_create_regex.")
    return await api.request("PATCH", f"/usernames/{username_id}", json=body)


@tool(DESTRUCTIVE)
async def delete_username(username_id: Id) -> Any:
    """Delete a username. Its aliases stop working."""
    return await api.request("DELETE", f"/usernames/{username_id}")


@tool(IDEMPOTENT)
async def set_username_default_recipient(
    username_id: Id,
    recipient_id: Annotated[str | None, Field(description="Recipient id, or null to use the account default")],
) -> Any:
    """Set (or clear) the default recipient for aliases on a username."""
    body = {"default_recipient": recipient_id}
    return await api.request("PATCH", f"/usernames/{username_id}/default-recipient", json=body)


@tool(IDEMPOTENT)
async def set_username_option(
    username_id: Id,
    option: Annotated[
        Literal["active", "catch_all", "can_login"],
        Field(
            description=(
                "'active': whether its aliases forward mail. "
                "'catch_all': auto-create aliases for any address at the username. "
                "'can_login': whether the username can be used to log in to the account."
            )
        ),
    ],
    enabled: bool,
) -> Any:
    """Turn a username option on or off."""
    resource = {
        "active": "active-usernames",
        "catch_all": "catch-all-usernames",
        "can_login": "loginable-usernames",
    }[option]
    return await _toggle(resource, username_id, enabled)


# --------------------------------------------------------------------------- domains


@tool(READ)
async def list_domains() -> Any:
    """List the custom domains connected to the account."""
    return await api.request("GET", "/domains")


@tool(READ)
async def get_domain(domain_id: Id) -> Any:
    """Get a single custom domain and its settings/verification status."""
    return await api.request("GET", f"/domains/{domain_id}")


@tool(WRITE)
async def create_domain(domain: Annotated[str, Field(description="Domain name, e.g. 'example.com'")]) -> Any:
    """Add a custom domain. Its DNS must already have the TXT verification record addy.io shows in its dashboard."""
    return await api.request("POST", "/domains", json={"domain": domain})


@tool(IDEMPOTENT)
async def update_domain(
    domain_id: Id,
    description: str | None = None,
    from_name: Annotated[str | None, Field(description="Display name for replies/sends")] = None,
    auto_create_regex: Annotated[
        str | None, Field(description="Regex limiting which on-the-fly aliases may be auto-created")
    ] = None,
) -> Any:
    """Update a custom domain's description, from name, or auto-create regex."""
    body = _body(description=description, from_name=from_name, auto_create_regex=auto_create_regex)
    if not body:
        raise ToolError("Provide at least one of description, from_name or auto_create_regex.")
    return await api.request("PATCH", f"/domains/{domain_id}", json=body)


@tool(DESTRUCTIVE)
async def delete_domain(domain_id: Id) -> Any:
    """Delete a custom domain. Its aliases stop working."""
    return await api.request("DELETE", f"/domains/{domain_id}")


@tool(IDEMPOTENT)
async def set_domain_default_recipient(
    domain_id: Id,
    recipient_id: Annotated[str | None, Field(description="Recipient id, or null to use the account default")],
) -> Any:
    """Set (or clear) the default recipient for aliases on a custom domain."""
    body = {"default_recipient": recipient_id}
    return await api.request("PATCH", f"/domains/{domain_id}/default-recipient", json=body)


@tool(READ)
async def check_domain_sending_records(domain_id: Id) -> Any:
    """Check a custom domain's DNS records (SPF, DKIM, DMARC, ...) for sending/replying from aliases."""
    return await api.request("POST", f"/domains/{domain_id}/check-sending")


@tool(IDEMPOTENT)
async def set_domain_option(
    domain_id: Id,
    option: Annotated[
        Literal["active", "catch_all", "shared_with_family"],
        Field(
            description=(
                "'active': whether its aliases forward mail. "
                "'catch_all': auto-create aliases for any address at the domain. "
                "'shared_with_family': share with Family plan members (turning off starts a 14-day grace period)."
            )
        ),
    ],
    enabled: bool,
) -> Any:
    """Turn a custom domain option on or off."""
    resource = {
        "active": "active-domains",
        "catch_all": "catch-all-domains",
        "shared_with_family": "shared-with-family-domains",
    }[option]
    return await _toggle(resource, domain_id, enabled)


# --------------------------------------------------------------------------- labels

LabelColour = Literal[
    "#06b6d4", "#22c55e", "#eab308", "#f97316", "#ef4444", "#8b5cf6", "#64748b", "#ec4899", "#14b8a6", "#3b82f6"
]
COLOUR_HELP = (
    "#06b6d4 cyan, #22c55e green, #eab308 yellow, #f97316 orange, #ef4444 red, "
    "#8b5cf6 violet, #64748b slate, #ec4899 pink, #14b8a6 teal, #3b82f6 blue"
)


@tool(READ)
async def list_labels(search: Annotated[str | None, Field(description="Search labels by name")] = None) -> Any:
    """List the labels used to organise aliases."""
    return await api.request("GET", "/labels", params={"filter[search]": search})


@tool(READ)
async def get_label(label_id: Id) -> Any:
    """Get a single label."""
    return await api.request("GET", f"/labels/{label_id}")


@tool(WRITE)
async def create_label(name: str, colour: Annotated[LabelColour, Field(description=COLOUR_HELP)]) -> Any:
    """Create a label for organising aliases."""
    return await api.request("POST", "/labels", json={"name": name, "colour": colour})


@tool(IDEMPOTENT)
async def update_label(
    label_id: Id,
    name: str | None = None,
    colour: Annotated[LabelColour | None, Field(description=COLOUR_HELP)] = None,
) -> Any:
    """Rename a label or change its colour."""
    body = _body(name=name, colour=colour)
    if not body:
        raise ToolError("Provide name and/or colour.")
    return await api.request("PATCH", f"/labels/{label_id}", json=body)


@tool(DESTRUCTIVE)
async def delete_label(label_id: Id) -> Any:
    """Delete a label (aliases are kept, just unlabelled)."""
    return await api.request("DELETE", f"/labels/{label_id}")


# --------------------------------------------------------------------------- rules


class RuleCondition(BaseModel):
    type: Literal[
        "sender", "subject", "alias", "alias_description", "alias_label", "display_from", "header",
        "alias_created_by_catch_all", "alias_not_created_by_catch_all", "has_attachments", "has_no_attachments",
        "email_is_spam", "email_is_not_spam", "dmarc_failed", "dmarc_did_not_fail", "email_size",
        "alias_emails_forwarded",
    ]  # fmt: skip
    match: str | None = Field(
        default=None,
        description=(
            "Text conditions: 'is exactly', 'is not', 'contains', 'does not contain', 'starts with', "
            "'does not start with', 'ends with', 'does not end with', 'matches regex', 'does not match regex'. "
            "header: 'exists', 'does not exist'. email_size/alias_emails_forwarded: 'is exactly', 'is not', "
            "'is greater than', 'is less than'. Omit for boolean condition types (has_attachments, etc.)."
        ),
    )
    values: list[str] | None = Field(
        default=None,
        description=(
            "Values to match (any of them). For header this is the header name, e.g. 'List-Unsubscribe'. "
            "For email_size use bytes. Omit for boolean condition types."
        ),
    )


class RuleAction(BaseModel):
    type: Literal[
        "subject", "displayFrom", "encryption", "banner", "block", "quarantine", "removeAttachments", "forwardTo",
        "blocklistSender", "blocklistDomain", "addLabel", "removeLabel", "setAliasDescription", "deactivateAlias",
        "deleteAlias", "webhook",
    ]  # fmt: skip
    value: str | dict[str, Any] | None = Field(
        default=None,
        description=(
            "subject/displayFrom: the new text. forwardTo: a recipient id. addLabel/removeLabel: the label name. "
            "setAliasDescription: the description ('' clears). webhook: an object "
            "{url: public https URL, include_body: bool, include_headers?: bool}."
        ),
    )


RuleOperator = Literal["AND", "OR"]


@tool(READ)
async def list_rules() -> Any:
    """List all rules, in the order they are applied."""
    return await api.request("GET", "/rules")


@tool(READ)
async def get_rule(rule_id: Id) -> Any:
    """Get a single rule with its conditions and actions."""
    return await api.request("GET", f"/rules/{rule_id}")


@tool(WRITE)
async def create_rule(
    name: str,
    conditions: Annotated[list[RuleCondition], Field(min_length=1)],
    actions: Annotated[list[RuleAction], Field(min_length=1)],
    operator: Annotated[RuleOperator, Field(description="Whether all (AND) or any (OR) conditions must match")] = "AND",
    forwards: Annotated[bool, Field(description="Apply to mail forwarded to recipients")] = True,
    replies: Annotated[bool, Field(description="Apply to replies sent from aliases")] = False,
    sends: Annotated[bool, Field(description="Apply to new emails sent from aliases")] = False,
) -> Any:
    """Create a rule that runs actions on emails matching conditions.

    Example: block newsletters to a specific alias -> conditions=[{type:'alias', match:'is exactly',
    values:['shop@anonaddy.me']}, {type:'header', match:'exists', values:['List-Unsubscribe']}],
    actions=[{type:'block'}].
    """
    body = {
        "name": name,
        "conditions": [c.model_dump(exclude_none=True) for c in conditions],
        "actions": [a.model_dump(exclude_none=True) for a in actions],
        "operator": operator,
        "forwards": forwards,
        "replies": replies,
        "sends": sends,
    }
    return await api.request("POST", "/rules", json=body)


@tool(IDEMPOTENT)
async def update_rule(
    rule_id: Id,
    name: str | None = None,
    conditions: Annotated[list[RuleCondition] | None, Field(description="Replaces all conditions")] = None,
    actions: Annotated[list[RuleAction] | None, Field(description="Replaces all actions")] = None,
    operator: RuleOperator | None = None,
    forwards: bool | None = None,
    replies: bool | None = None,
    sends: bool | None = None,
) -> Any:
    """Update a rule. Only the fields you pass change; the rest are kept from the current rule."""
    current = (await api.request("GET", f"/rules/{rule_id}"))["data"]
    body = {
        "name": name if name is not None else current["name"],
        "conditions": (
            [c.model_dump(exclude_none=True) for c in conditions] if conditions is not None else current["conditions"]
        ),
        "actions": [a.model_dump(exclude_none=True) for a in actions] if actions is not None else current["actions"],
        "operator": operator or current["operator"],
        "forwards": forwards if forwards is not None else current["forwards"],
        "replies": replies if replies is not None else current["replies"],
        "sends": sends if sends is not None else current["sends"],
    }
    return await api.request("PATCH", f"/rules/{rule_id}", json=body)


@tool(DESTRUCTIVE)
async def delete_rule(rule_id: Id) -> Any:
    """Delete a rule."""
    return await api.request("DELETE", f"/rules/{rule_id}")


@tool(IDEMPOTENT)
async def reorder_rules(rule_ids: Annotated[IdList, Field(description="All rule ids, in the new order")]) -> Any:
    """Set the order rules are applied in."""
    return await api.request("POST", "/reorder-rules", json={"ids": rule_ids})


@tool(IDEMPOTENT)
async def set_rule_active(rule_id: Id, active: bool) -> Any:
    """Activate or deactivate a rule."""
    return await _toggle("active-rules", rule_id, active)


# --------------------------------------------------------------------------- blocklist


@tool(READ)
async def list_blocklist(
    search: Annotated[str | None, Field(description="Search by email or domain")] = None,
    type: Literal["email", "domain"] | None = None,
    sort: Literal["created_at", "value", "blocked", "last_blocked"] | None = None,
    descending: bool = False,
    page: Page = None,
    page_size: PageSize = None,
) -> Any:
    """List blocked senders/domains, with how many emails each has blocked."""
    params = {
        "filter[search]": search,
        "filter[type]": type,
        "sort": f"-{sort}" if sort and descending else sort,
        "page[number]": page,
        "page[size]": page_size,
    }
    return await api.request("GET", "/blocklist", params=params)


@tool(WRITE)
async def add_to_blocklist(
    type: Annotated[Literal["email", "domain"], Field(description="Whether values are email addresses or domains")],
    values: Annotated[
        list[str], Field(description="Addresses or domains to block (max 50)", min_length=1, max_length=50)
    ],
) -> Any:
    """Block mail from sender email addresses or whole domains, across all aliases."""
    if len(values) == 1:
        return await api.request("POST", "/blocklist", json={"type": type, "value": values[0]})
    return await api.request("POST", "/blocklist/store/bulk", json={"type": type, "values": values})


@tool(DESTRUCTIVE)
async def remove_from_blocklist(
    entry_ids: Annotated[IdList, Field(description="Blocklist entry ids (max 100)", min_length=1, max_length=100)],
) -> Any:
    """Unblock blocklist entries by id (see list_blocklist)."""
    if len(entry_ids) == 1:
        return await api.request("DELETE", f"/blocklist/{entry_ids[0]}")
    return await api.request("POST", "/blocklist/delete/bulk", json={"ids": entry_ids})


# --------------------------------------------------------------------------- failed deliveries

MAX_EMAIL_CHARS = 100_000


@tool(READ)
async def list_failed_deliveries(
    email_type: Annotated[
        Literal["inbound", "outbound", "inbound_quarantined"] | None,
        Field(description="Filter by type; 'inbound_quarantined' shows mail quarantined by rules or spam checks"),
    ] = None,
    page: Page = None,
    page_size: PageSize = None,
) -> Any:
    """List emails that addy.io failed to deliver (or quarantined)."""
    params = {"filter[email_type]": email_type, "page[number]": page, "page[size]": page_size}
    return await api.request("GET", "/failed-deliveries", params=params)


@tool(READ)
async def get_failed_delivery(failed_delivery_id: Id) -> Any:
    """Get details of a failed delivery (sender, alias, bounce reason, ...)."""
    return await api.request("GET", f"/failed-deliveries/{failed_delivery_id}")


@tool(READ)
async def download_failed_delivery(failed_delivery_id: Id) -> str:
    """Download the raw email (.eml source) of a failed delivery, if addy.io stored it."""
    text = await api.request("GET", f"/failed-deliveries/{failed_delivery_id}/download", raw=True)
    if not text:
        return "No stored email is available for this failed delivery."
    if len(text) > MAX_EMAIL_CHARS:
        return text[:MAX_EMAIL_CHARS] + f"\n\n[truncated: showing {MAX_EMAIL_CHARS:,} of {len(text):,} characters]"
    return text


@tool(WRITE)
async def resend_failed_delivery(
    failed_delivery_id: Id,
    recipient_ids: Annotated[
        IdList | None, Field(description="Recipients to resend to (max 10); defaults to the alias's recipients")
    ] = None,
) -> Any:
    """Retry delivering a failed or quarantined email."""
    body = _body(recipient_ids=recipient_ids)
    return await api.request("POST", f"/failed-deliveries/{failed_delivery_id}/resend", json=body)


@tool(DESTRUCTIVE)
async def delete_failed_deliveries(
    failed_delivery_ids: Annotated[IdList, Field(description="Ids to delete (max 100)", min_length=1, max_length=100)],
) -> Any:
    """Delete failed delivery records (and any stored email)."""
    if len(failed_delivery_ids) == 1:
        return await api.request("DELETE", f"/failed-deliveries/{failed_delivery_ids[0]}")
    return await api.request("POST", "/failed-deliveries/delete/bulk", json={"ids": failed_delivery_ids})


def apply_read_only_mode() -> None:
    """Remove every tool that can change the account."""
    for name in WRITE_TOOLS:
        mcp.remove_tool(name)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="addy-mcp",
        description=(
            "MCP server for addy.io. Started by an MCP client (e.g. Claude) over stdio; "
            "set ADDY_API_KEY in its environment."
        ),
    )
    parser.add_argument("--version", action="version", version=f"addy-mcp {__version__}")
    parser.parse_args(argv)

    if os.environ.get(READ_ONLY_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        apply_read_only_mode()
    mcp.run()


if __name__ == "__main__":
    main()
