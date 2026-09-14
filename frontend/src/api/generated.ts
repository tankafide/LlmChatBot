export interface paths {
    "/dealerships": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Dealerships
         * @description Return the configured dealership list, or a 503 JSON error if storage is unavailable.
         *
         *     Called for GET /dealerships.
         */
        get: operations["list_dealerships_dealerships_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/dealerships/{dealership_id}/conversations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Conversation
         * @description Create or recover a conversation using creation_id. Return its public identity under HTTP
         *     201, or the application error response; no message is submitted here.
         *
         *     Called for POST /dealerships/{dealership_id}/conversations, normally before the first
         *     message of a new chat.
         */
        post: operations["create_conversation_dealerships__dealership_id__conversations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/dealerships/{dealership_id}/conversations/{conversation_id}/messages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Conversation Messages
         * @description Return a page of durable messages and a continuation sequence (None at the end), or a JSON
         *     application error. Failed user turns remain visible. History is the durable user-visible
         *     record, including failed user turns. It is distinct from the completed tool/model replay
         *     supplied to the LLM.
         *
         *     Called when the browser loads, paginates, or reconciles conversation history.
         */
        get: operations["get_conversation_messages_dealerships__dealership_id__conversations__conversation_id__messages_get"];
        put?: never;
        /**
         * Submit Message
         * @description Submit immutable request ID/text to the lifecycle service. Return JSON with 202 acceptance,
         *     a replayed terminal outcome, or an application error status. Chat routes await async
         *     orchestration. Submission can return 202 for admitted work or a stored terminal outcome for
         *     a retry; the service chooses that status.
         *
         *     Called for every POST to a conversation messages collection, including retries. The
         *     conversation must already exist.
         */
        post: operations["submit_message_dealerships__dealership_id__conversations__conversation_id__messages_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/dealerships/{dealership_id}/conversations/{conversation_id}/requests/{request_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Request Status
         * @description Return an uncached JSON status snapshot, including a terminal outcome when settled. Missing
         *     requests/storage failures return the application error response.
         *
         *     Called when the browser polls GET requests/{request_id} for an admitted or uncertain turn.
         */
        get: operations["get_request_status_dealerships__dealership_id__conversations__conversation_id__requests__request_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/dealerships/{dealership_id}/vehicles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Search Inventory
         * @description Translate validated query filters and return a vehicle page with its next cursor. Return 404
         *     for missing scope or 503 for unavailable storage.
         *
         *     Called for GET /dealerships/{dealership_id}/vehicles after query validation.
         */
        get: operations["search_inventory_dealerships__dealership_id__vehicles_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/dealerships/{dealership_id}/vehicles/{vehicle_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Vehicle
         * @description Return one dealership-scoped vehicle detail, or a 404/503 JSON error for missing
         *     inventory/unavailable storage.
         *
         *     Called for GET /dealerships/{dealership_id}/vehicles/{vehicle_id}.
         */
        get: operations["get_vehicle_dealerships__dealership_id__vehicles__vehicle_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description Probe required storage tables. Return an ok health model or a 503 error response for
         *     recognized storage outages; unexpected database defects propagate. This synchronous route
         *     checks storage without depending on paid/external APIs. FastAPI runs ordinary def handlers
         *     in its thread pool for blocking database work.
         *
         *     Called for GET /health.
         */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * AcceptedRequestResponse
         * @description Acknowledge durable admission with status in_progress and request identity.
         *
         *     It does not promise completion; clients poll the request status for the final outcome.
         */
        AcceptedRequestResponse: {
            /**
             * Conversation Id
             * Format: uuid
             */
            conversation_id: string;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            status: "in_progress";
        };
        /**
         * CompletedRequestStatus
         * @description Represent a successful terminal result inside the status endpoint response.
         *
         *     Its completed discriminator carries the full saved completion outcome.
         */
        CompletedRequestStatus: {
            /**
             * Conversation Id
             * Format: uuid
             */
            conversation_id: string;
            outcome: components["schemas"]["SubmitMessageResponse"];
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            status: "completed";
        };
        /**
         * ConversationHistoryResponse
         * @description Expose a page of durable conversation history and current selection.
         *
         *     next_after_sequence is null at the end; history includes admitted unsuccessful user turns.
         */
        ConversationHistoryResponse: {
            /**
             * Conversation Id
             * Format: uuid
             */
            conversation_id: string;
            /** Items */
            items: components["schemas"]["ConversationMessageResponse"][];
            /** Next After Sequence */
            next_after_sequence: number | null;
            /** Selected Vehicle Id */
            selected_vehicle_id: string | null;
        };
        /**
         * ConversationMessageResponse
         * @description Expose a saved user or assistant message with server sequence and request status.
         *
         *     A failed/interrupted user message remains visible even when no assistant reply exists.
         */
        ConversationMessageResponse: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Error Code */
            error_code: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /**
             * Request Status
             * @enum {string}
             */
            request_status: "in_progress" | "completed" | "failed" | "interrupted";
            /**
             * Role
             * @enum {string}
             */
            role: "user" | "assistant";
            /** Sequence */
            sequence: number;
            /** Text */
            text: string;
        };
        /**
         * ConversationResponse
         * @description Expose the created or recovered conversation identity and public selection field.
         *
         *     Provider configuration and model replay stay internal.
         */
        ConversationResponse: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Dealership Id
             * Format: uuid
             */
            dealership_id: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Selected Vehicle Id */
            selected_vehicle_id: string | null;
        };
        /**
         * CreateConversationRequest
         * @description Identify a conversation-creation attempt independently of message submission.
         *
         *     Reusing creation_id within a dealership recovers the same conversation after an uncertain
         *     response.
         */
        CreateConversationRequest: {
            /**
             * Creation Id
             * Format: uuid
             */
            creation_id: string;
        };
        /**
         * DealershipListResponse
         * @description Wrap the publicly listed dealership records; items may be empty.
         */
        DealershipListResponse: {
            /** Items */
            items: components["schemas"]["DealershipResponse"][];
        };
        /**
         * DealershipResponse
         * @description Expose a dealership UUID, configured slug, and display name without internal connection
         *     settings.
         */
        DealershipResponse: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Name */
            name: string;
            /** Slug */
            slug: string;
        };
        /**
         * ErrorDetail
         * @description Carry a public machine-readable error code and human-readable message.
         *
         *     Consumers use the code to distinguish retry, rejection, and terminal failure behavior.
         */
        ErrorDetail: {
            /** Code */
            code: string;
            /** Message */
            message: string;
        };
        /**
         * ErrorEnvelope
         * @description Wrap a public application error under the error key for consistent HTTP handling.
         */
        ErrorEnvelope: {
            error: components["schemas"]["ErrorDetail"];
        };
        /**
         * FailedRequestStatus
         * @description Represent failed or interrupted execution in a successful status lookup.
         *
         *     The nested error explains the turn failure; HTTP status retrieval can still return 200.
         */
        FailedRequestStatus: {
            /**
             * Conversation Id
             * Format: uuid
             */
            conversation_id: string;
            outcome: components["schemas"]["ErrorEnvelope"];
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            status: "failed" | "interrupted";
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /**
         * HealthResponse
         * @description Represent the successful storage health response.
         *
         *     It does not claim external model or NHTSA availability.
         */
        HealthResponse: {
            /** Status */
            status: string;
        };
        /**
         * InventoryPageResponse
         * @description Carry one public inventory page and its continuation UUID.
         *
         *     next_after is null at the end; an empty items list is a valid search result.
         */
        InventoryPageResponse: {
            /** Items */
            items: components["schemas"]["VehicleResponse"][];
            /** Next After */
            next_after: string | null;
        };
        /**
         * SubmitMessageRequest
         * @description Validate one immutable client request ID and its message text.
         *
         *     Whitespace-only text is rejected without trimming valid payloads, preserving equality for
         *     same-ID retries.
         */
        SubmitMessageRequest: {
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /** Text */
            text: string;
        };
        /**
         * SubmitMessageResponse
         * @description Represent the stored completed-turn response used for terminal replay.
         *
         *     Includes both messages and resulting selection; new asynchronous admission is represented
         *     separately.
         */
        SubmitMessageResponse: {
            assistant_message: components["schemas"]["ConversationMessageResponse"];
            /**
             * Conversation Id
             * Format: uuid
             */
            conversation_id: string;
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /** Selected Vehicle Id */
            selected_vehicle_id: string | null;
            /**
             * Status
             * @constant
             */
            status: "completed";
            user_message: components["schemas"]["ConversationMessageResponse"];
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /**
         * VehicleDetailResponse
         * @description Extend the public vehicle summary with supported specifications.
         *
         *     Unknown optional facts remain null so clients cannot mistake missing data for confirmed
         *     values.
         */
        VehicleDetailResponse: {
            /** Body Type */
            body_type: string | null;
            /** Condition */
            condition: string | null;
            /** Drivetrain */
            drivetrain: string | null;
            /** Exterior Color */
            exterior_color: string | null;
            /** Fuel */
            fuel: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Make */
            make: string;
            /** Mileage */
            mileage: number | null;
            /** Model */
            model: string;
            /** Price */
            price: string | null;
            /** Source Id */
            source_id: string;
            /** Transmission */
            transmission: string | null;
            /** Trim */
            trim: string | null;
            /** Year */
            year: number;
        };
        /**
         * VehicleResponse
         * @description Expose an inventory summary with decimal price text and dealership-local stock number.
         *
         *     Nullable price/body fields represent unknown inventory data, not zero or empty facts.
         */
        VehicleResponse: {
            /** Body Type */
            body_type: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Make */
            make: string;
            /** Model */
            model: string;
            /** Price */
            price: string | null;
            /** Source Id */
            source_id: string;
            /** Year */
            year: number;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_dealerships_dealerships_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DealershipListResponse"];
                };
            };
            /** @description Inventory storage unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    create_conversation_dealerships__dealership_id__conversations_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dealership_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateConversationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConversationResponse"];
                };
            };
            /** @description Conversation or dealership not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Request conflict or interruption */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Sanitized internal failure */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Chat provider failure */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Connection, capacity, or storage unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Chat provider timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    get_conversation_messages_dealerships__dealership_id__conversations__conversation_id__messages_get: {
        parameters: {
            query?: {
                after_sequence?: number;
                limit?: number;
            };
            header?: never;
            path: {
                dealership_id: string;
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConversationHistoryResponse"];
                };
            };
            /** @description Conversation or dealership not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Request conflict or interruption */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Sanitized internal failure */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Chat provider failure */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Connection, capacity, or storage unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Chat provider timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    submit_message_dealerships__dealership_id__conversations__conversation_id__messages_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dealership_id: string;
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SubmitMessageRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SubmitMessageResponse"];
                };
            };
            /** @description Accepted */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AcceptedRequestResponse"];
                };
            };
            /** @description Conversation or dealership not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Request conflict or interruption */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Sanitized internal failure */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Chat provider failure */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Connection, capacity, or storage unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Chat provider timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    get_request_status_dealerships__dealership_id__conversations__conversation_id__requests__request_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dealership_id: string;
                conversation_id: string;
                request_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AcceptedRequestResponse"] | components["schemas"]["CompletedRequestStatus"] | components["schemas"]["FailedRequestStatus"];
                };
            };
            /** @description Conversation or dealership not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Connection, capacity, or storage unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    search_inventory_dealerships__dealership_id__vehicles_get: {
        parameters: {
            query?: {
                make?: string | null;
                model?: string | null;
                body_type?: string | null;
                year_min?: number | null;
                year_max?: number | null;
                price_min?: number | string | null;
                price_max?: number | string | null;
                limit?: number;
                after?: string | null;
            };
            header?: never;
            path: {
                dealership_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InventoryPageResponse"];
                };
            };
            /** @description Dealership or vehicle not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Inventory storage unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    get_vehicle_dealerships__dealership_id__vehicles__vehicle_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                dealership_id: string;
                vehicle_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VehicleDetailResponse"];
                };
            };
            /** @description Dealership or vehicle not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Inventory storage unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
}
