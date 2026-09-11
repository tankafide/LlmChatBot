export interface paths {
    "/dealerships": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Dealerships */
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
        /** Create Conversation */
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
        /** Get Conversation Messages */
        get: operations["get_conversation_messages_dealerships__dealership_id__conversations__conversation_id__messages_get"];
        put?: never;
        /** Submit Message */
        post: operations["submit_message_dealerships__dealership_id__conversations__conversation_id__messages_post"];
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
        /** Search Inventory */
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
        /** Get Vehicle */
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
        /** Health */
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
        /** ConversationHistoryResponse */
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
        /** ConversationMessageResponse */
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
        /** ConversationResponse */
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
        /** CreateConversationRequest */
        CreateConversationRequest: Record<string, never>;
        /** DealershipListResponse */
        DealershipListResponse: {
            /** Items */
            items: components["schemas"]["DealershipResponse"][];
        };
        /** DealershipResponse */
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
        /** ErrorDetail */
        ErrorDetail: {
            /** Code */
            code: string;
            /** Message */
            message: string;
        };
        /** ErrorEnvelope */
        ErrorEnvelope: {
            error: components["schemas"]["ErrorDetail"];
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HealthResponse */
        HealthResponse: {
            /** Status */
            status: string;
        };
        /** InventoryPageResponse */
        InventoryPageResponse: {
            /** Items */
            items: components["schemas"]["VehicleResponse"][];
            /** Next After */
            next_after: string | null;
        };
        /** SubmitMessageRequest */
        SubmitMessageRequest: {
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /** Text */
            text: string;
        };
        /** SubmitMessageResponse */
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
        /** VehicleDetailResponse */
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
        /** VehicleResponse */
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
