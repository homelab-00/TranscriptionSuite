import { useState, useEffect, useRef } from 'react';
import {
  MessageSquare,
  Plus,
  Send,
  Loader2,
  Trash2,
  Edit2,
  Check,
  X,
  Power,
  PowerOff,
  ChevronRight,
  ChevronDown,
  RefreshCw,
  Settings,
} from 'lucide-react';
import { api } from '../services/api';
import { Conversation, ConversationWithMessages, Message, LLMStatus } from '../types';

// Preset system prompts
const SYSTEM_PROMPTS = [
  {
    id: 'default',
    name: 'Default Assistant',
    prompt: 'You are a helpful assistant that analyzes transcriptions. When given a transcription, provide clear and insightful responses. Respond in the same language as the transcription.',
  },
  {
    id: 'summarize',
    name: 'Summarizer',
    prompt: 'Summarize the transcription concisely, highlighting the main points, key topics discussed, and any action items. Respond in the same language as the transcription.',
  },
  {
    id: 'qa',
    name: 'Q&A Assistant',
    prompt: 'Answer questions about the transcription accurately and concisely. If the answer is not in the transcription, say so. Respond in the same language as the question.',
  },
  {
    id: 'translate',
    name: 'Translator',
    prompt: 'Translate or explain content from the transcription as requested. Be accurate and maintain the original meaning.',
  },
  {
    id: 'none',
    name: 'No System Prompt',
    prompt: '',
  },
  {
    id: 'custom',
    name: 'Custom...',
    prompt: '',
  },
];

interface ChatPanelProps {
  recordingId: number;
  isOpen: boolean;
  onClose: () => void;
}

export default function ChatPanel({ recordingId, isOpen, onClose }: ChatPanelProps) {
  // LLM Status
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmError, setLlmError] = useState<string | null>(null);

  // Conversations
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<ConversationWithMessages | null>(null);
  const [conversationsExpanded, setConversationsExpanded] = useState(true);

  // System prompt selection
  const [selectedPromptId, setSelectedPromptId] = useState('default');
  const [customPrompt, setCustomPrompt] = useState('');
  const [showPromptSettings, setShowPromptSettings] = useState(false);

  // Chat input
  const [inputMessage, setInputMessage] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const abortControllerRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Editing
  const [editingTitleId, setEditingTitleId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState('');

  // Get the current system prompt based on selection
  const getCurrentSystemPrompt = (): string | undefined => {
    if (selectedPromptId === 'custom') {
      return customPrompt || undefined;
    }
    if (selectedPromptId === 'none') {
      return undefined;
    }
    const preset = SYSTEM_PROMPTS.find(p => p.id === selectedPromptId);
    return preset?.prompt || undefined;
  };

  useEffect(() => {
    if (isOpen && recordingId) {
      loadConversations();
      checkLLMStatus();
    }
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [isOpen, recordingId]);

  useEffect(() => {
    // Scroll to bottom when new messages arrive
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeConversation?.messages, streamingContent]);

  const checkLLMStatus = async () => {
    try {
      const status = await api.getLLMStatus();
      setLlmStatus(status);
    } catch {
      setLlmStatus({ available: false, base_url: '', model: null, error: 'Failed to check status' });
    }
  };

  const loadConversations = async () => {
    try {
      const convos = await api.getConversations(recordingId);
      setConversations(convos);
      // If there's an active conversation, reload it
      if (activeConversation) {
        const updated = await api.getConversation(activeConversation.id);
        setActiveConversation(updated);
      }
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const handleStartLLM = async () => {
    setLlmLoading(true);
    setLlmError(null);
    try {
      // First start the server
      const serverResult = await api.startLMStudioServer();
      if (!serverResult.success && !serverResult.message.includes('already running')) {
        setLlmError(serverResult.message);
        setLlmLoading(false);
        return;
      }

      // Then load the model
      const modelResult = await api.loadModel();
      if (!modelResult.success) {
        setLlmError(modelResult.message);
        setLlmLoading(false);
        return;
      }

      // Refresh status
      await checkLLMStatus();
    } catch (error) {
      setLlmError((error as Error).message);
    } finally {
      setLlmLoading(false);
    }
  };

  const handleStopLLM = async () => {
    setLlmLoading(true);
    setLlmError(null);
    try {
      const result = await api.unloadModel(true);
      if (!result.success) {
        setLlmError(result.message);
      }
      await checkLLMStatus();
    } catch (error) {
      setLlmError((error as Error).message);
    } finally {
      setLlmLoading(false);
    }
  };

  const handleNewConversation = async () => {
    try {
      const result = await api.createConversation(recordingId, 'New Chat');
      await loadConversations();
      // Open the new conversation
      const newConvo = await api.getConversation(result.conversation_id);
      setActiveConversation(newConvo);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = async (conversationId: number) => {
    try {
      const convo = await api.getConversation(conversationId);
      setActiveConversation(convo);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const handleDeleteConversation = async (conversationId: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this conversation?')) return;

    try {
      await api.deleteConversation(conversationId);
      if (activeConversation?.id === conversationId) {
        setActiveConversation(null);
      }
      await loadConversations();
    } catch (error) {
      console.error('Failed to delete conversation:', error);
    }
  };

  const handleStartEditTitle = (conversation: Conversation, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingTitleId(conversation.id);
    setEditingTitle(conversation.title);
  };

  const handleSaveTitle = async (conversationId: number) => {
    try {
      await api.updateConversationTitle(conversationId, editingTitle);
      await loadConversations();
      setEditingTitleId(null);
    } catch (error) {
      console.error('Failed to update title:', error);
    }
  };

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || !activeConversation || isSending) return;

    // Check LLM availability
    if (!llmStatus?.available) {
      setLlmError('LLM is not available. Click "Start LLM" to load a model.');
      return;
    }

    const userMessage = inputMessage.trim();
    setInputMessage('');
    setIsSending(true);
    setStreamingContent('');
    setLlmError(null);

    // Optimistically add user message to UI
    const tempUserMessage: Message = {
      id: -1,
      conversation_id: activeConversation.id,
      role: 'user',
      content: userMessage,
      created_at: new Date().toISOString(),
    };
    setActiveConversation(prev => prev ? {
      ...prev,
      messages: [...prev.messages, tempUserMessage],
    } : null);

    try {
      abortControllerRef.current = await api.chat(
        {
          conversation_id: activeConversation.id,
          user_message: userMessage,
          include_transcription: true,
          system_prompt: getCurrentSystemPrompt(),
        },
        (content) => {
          setStreamingContent(prev => prev + content);
        },
        async () => {
          setIsSending(false);
          setStreamingContent('');
          // Reload conversation to get the saved messages
          const updated = await api.getConversation(activeConversation.id);
          setActiveConversation(updated);
        },
        (error) => {
          setLlmError(error);
          setIsSending(false);
          setStreamingContent('');
          // Reload to show actual state
          loadConversations();
          handleSelectConversation(activeConversation.id);
        }
      );
    } catch (error) {
      setLlmError((error as Error).message);
      setIsSending(false);
    }
  };

  const handleStopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsSending(false);
    setStreamingContent('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed right-0 top-0 h-full w-96 bg-surface border-l border-gray-700 flex flex-col shadow-xl z-50">
      {/* Header */}
      <div className="p-4 border-b border-gray-700 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MessageSquare size={20} className="text-purple-400" />
          <h2 className="text-lg font-medium text-white">Chat with AI</h2>
        </div>
        <button onClick={onClose} className="btn-icon p-1">
          <X size={20} />
        </button>
      </div>

      {/* LLM Status Bar */}
      <div className="px-4 py-2 border-b border-gray-700 bg-surface-dark">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <span className={`w-2 h-2 rounded-full ${llmStatus?.available ? 'bg-green-500' : 'bg-red-500'}`} />
            <span className="text-gray-400">
              {llmStatus?.available 
                ? (llmStatus.model || 'Model loaded')
                : 'LLM not loaded'}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowPromptSettings(!showPromptSettings)}
              className={`btn-icon p-1 ${showPromptSettings ? 'text-purple-400' : ''}`}
              title="Prompt settings"
            >
              <Settings size={14} />
            </button>
            <button
              onClick={checkLLMStatus}
              className="btn-icon p-1"
              title="Refresh status"
              disabled={llmLoading}
            >
              <RefreshCw size={14} className={llmLoading ? 'animate-spin' : ''} />
            </button>
            {llmStatus?.available ? (
              <button
                onClick={handleStopLLM}
                className="btn-ghost text-red-400 hover:text-red-300 text-xs flex items-center gap-1"
                disabled={llmLoading}
              >
                <PowerOff size={14} />
                Stop
              </button>
            ) : (
              <button
                onClick={handleStartLLM}
                className="btn-ghost text-green-400 hover:text-green-300 text-xs flex items-center gap-1"
                disabled={llmLoading}
              >
                {llmLoading ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Power size={14} />
                )}
                Start LLM
              </button>
            )}
          </div>
        </div>
        {llmError && (
          <p className="text-red-400 text-xs mt-1">{llmError}</p>
        )}
      </div>

      {/* System Prompt Settings */}
      {showPromptSettings && (
        <div className="px-4 py-3 border-b border-gray-700 bg-surface-dark/50">
          <label className="text-xs text-gray-400 block mb-2">System Prompt</label>
          <select
            value={selectedPromptId}
            onChange={(e) => setSelectedPromptId(e.target.value)}
            className="w-full bg-surface-dark border border-gray-600 rounded px-2 py-1.5 text-sm text-white mb-2"
          >
            {SYSTEM_PROMPTS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          
          {selectedPromptId === 'custom' && (
            <textarea
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              placeholder="Enter your custom system prompt..."
              className="w-full bg-surface-dark border border-gray-600 rounded px-2 py-1.5 text-sm text-white resize-none h-20"
            />
          )}
          
          {selectedPromptId !== 'custom' && selectedPromptId !== 'none' && (
            <p className="text-xs text-gray-500 italic">
              {SYSTEM_PROMPTS.find(p => p.id === selectedPromptId)?.prompt}
            </p>
          )}
        </div>
      )}

      {/* Conversations List */}
      <div className="border-b border-gray-700">
        <button
          onClick={() => setConversationsExpanded(!conversationsExpanded)}
          className="w-full px-4 py-2 flex items-center justify-between hover:bg-surface-light transition-colors"
        >
          <span className="text-sm text-gray-400">Conversations</span>
          {conversationsExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        
        {conversationsExpanded && (
          <div className="px-2 pb-2 max-h-40 overflow-y-auto">
            <button
              onClick={handleNewConversation}
              className="w-full px-2 py-1.5 text-sm text-purple-400 hover:bg-surface-light rounded flex items-center gap-2"
            >
              <Plus size={14} />
              New Chat
            </button>
            
            {conversations.map((convo) => (
              <div
                key={convo.id}
                onClick={() => handleSelectConversation(convo.id)}
                className={`
                  px-2 py-1.5 rounded cursor-pointer flex items-center justify-between group
                  ${activeConversation?.id === convo.id 
                    ? 'bg-purple-900/30 text-white' 
                    : 'text-gray-300 hover:bg-surface-light'}
                `}
              >
                {editingTitleId === convo.id ? (
                  <div className="flex items-center gap-1 flex-1" onClick={e => e.stopPropagation()}>
                    <input
                      type="text"
                      value={editingTitle}
                      onChange={(e) => setEditingTitle(e.target.value)}
                      className="flex-1 bg-surface-dark px-1 py-0.5 text-sm rounded border border-gray-600"
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleSaveTitle(convo.id);
                        if (e.key === 'Escape') setEditingTitleId(null);
                      }}
                    />
                    <button onClick={() => handleSaveTitle(convo.id)} className="p-0.5">
                      <Check size={12} className="text-green-400" />
                    </button>
                    <button onClick={() => setEditingTitleId(null)} className="p-0.5">
                      <X size={12} className="text-red-400" />
                    </button>
                  </div>
                ) : (
                  <>
                    <span className="text-sm truncate flex-1">{convo.title}</span>
                    <div className="hidden group-hover:flex items-center gap-0.5">
                      <button 
                        onClick={(e) => handleStartEditTitle(convo, e)}
                        className="p-0.5 hover:text-purple-400"
                      >
                        <Edit2 size={12} />
                      </button>
                      <button 
                        onClick={(e) => handleDeleteConversation(convo.id, e)}
                        className="p-0.5 hover:text-red-400"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
            
            {conversations.length === 0 && (
              <p className="text-xs text-gray-500 px-2 py-1">No conversations yet</p>
            )}
          </div>
        )}
      </div>

      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {!activeConversation ? (
          <div className="text-center text-gray-500 mt-8">
            <MessageSquare size={40} className="mx-auto mb-3 opacity-50" />
            <p>Select or create a conversation to start chatting</p>
          </div>
        ) : (
          <>
            {activeConversation.messages.map((msg, idx) => (
              <div
                key={msg.id !== -1 ? msg.id : `temp-${idx}`}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`
                    max-w-[85%] rounded-lg px-3 py-2 text-sm
                    ${msg.role === 'user'
                      ? 'bg-purple-600 text-white'
                      : 'bg-surface-light text-gray-200'}
                  `}
                >
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                </div>
              </div>
            ))}
            
            {/* Streaming response */}
            {streamingContent && (
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-lg px-3 py-2 text-sm bg-surface-light text-gray-200">
                  <p className="whitespace-pre-wrap">
                    {streamingContent}
                    <span className="inline-block w-2 h-4 bg-purple-400 ml-0.5 animate-pulse" />
                  </p>
                </div>
              </div>
            )}
            
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input Area */}
      {activeConversation && (
        <div className="p-4 border-t border-gray-700">
          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a message..."
              disabled={isSending || !llmStatus?.available}
              className="flex-1 bg-surface-dark border border-gray-600 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 resize-none focus:outline-none focus:border-purple-500 disabled:opacity-50"
              rows={2}
            />
            {isSending ? (
              <button
                onClick={handleStopGeneration}
                className="btn-icon p-2 text-red-400 hover:text-red-300"
              >
                <X size={20} />
              </button>
            ) : (
              <button
                onClick={handleSendMessage}
                disabled={!inputMessage.trim() || !llmStatus?.available}
                className="btn-icon p-2 text-purple-400 hover:text-purple-300 disabled:opacity-50"
              >
                <Send size={20} />
              </button>
            )}
          </div>
          {!llmStatus?.available && (
            <p className="text-xs text-gray-500 mt-2">
              Start the LLM to send messages
            </p>
          )}
        </div>
      )}
    </div>
  );
}
